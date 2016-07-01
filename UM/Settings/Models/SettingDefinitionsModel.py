# Copyright (c) 2016 Ultimaker B.V.
# Uranium is released under the terms of the AGPLv3 or higher.

import collections
import itertools

from PyQt5.QtCore import Qt, QAbstractListModel, QVariant, QModelIndex, pyqtProperty, pyqtSignal, pyqtSlot

from UM.Logger import Logger
from UM.Preferences import Preferences

import UM.Settings

##  Model that provides a flattened list of the tree of SettingDefinition objects in a DefinitionContainer
#
#   This model exposes the tree of SettingDefinition objects in a DefinitionContainer as a list of settings.
#   It uses two lists, one is the list of definitions which directly corresponds with the flattened contents
#   of the DefinitionContainer. The other is a list matching rows in the model to indexes in the list of
#   settings. This list can be quite a bit shorter than the list of definitions since all visibility criteria
#   are applied.
#
class SettingDefinitionsModel(QAbstractListModel):
    KeyRole = Qt.UserRole + 1
    DepthRole = Qt.UserRole + 2
    VisibleRole = Qt.UserRole + 3
    ExpandedRole = Qt.UserRole + 4

    def __init__(self, parent = None, *args, **kwargs):
        super().__init__(parent = parent, *args, **kwargs)

        self._container_id = None
        self._container = None

        self._root_key = ""
        self._root = None

        self._definition_list = []
        self._row_index_list = []

        self._expanded = set()
        self._visible = set()
        self._exclude = set()

        self._show_all = False

        self._visibility_handler = None

        self._filter_dict = {}

        self._role_names = {
            self.KeyRole: b"key",
            self.DepthRole: b"depth",
            self.VisibleRole: b"visible",
            self.ExpandedRole: b"expanded",
        }
        index = self.ExpandedRole + 1
        for name in UM.Settings.SettingDefinition.getPropertyNames():
            self._role_names[index] = name.encode()
            index += 1

    ##  Set the containerId property.
    def setContainerId(self, container_id):
        if container_id != self._container_id:
            self._container_id = container_id

            containers = UM.Settings.ContainerRegistry.getInstance().findDefinitionContainers(id = self._container_id)
            if containers:
                self._container = containers[0]
            else:
                self._container = None

            self._update()
            self.containerIdChanged.emit()

    ##  Emitted whenever the containerId property changes.
    containerIdChanged = pyqtSignal()
    ##  The ID of the DefinitionContainer object this model exposes.
    @pyqtProperty(str, fset = setContainerId, notify = containerIdChanged)
    def containerId(self):
        return self._container_id

    ##  Set the rootKey property.
    def setRootKey(self, key):
        if key != self._root_key:
            self._root_key = key

            if self._container:
                definitions = self._container.findDefinitions(key = key)
                if not definitions:
                    Logger.log("w", "Tried to set root of SettingDefinitionsModel to an unknown definition")
                    return

                self._root = definitions[0]
                self._update()

            self.rootKeyChanged.emit()

    ##  Emitted when the rootKey property changes.
    rootKeyChanged = pyqtSignal()
    ##  The SettingDefinition to use as root for the list.
    @pyqtProperty(str, fset = setRootKey, notify = rootKeyChanged)
    def rootKey(self):
        return self._root_key

    ##  Set the showAll property.
    def setShowAll(self, show):
        if show != self._show_all:
            self._show_all = show
            self.showAllChanged.emit()
            self._updateVisibleRows()

    ##  Emitted when the showAll property changes.
    showAllChanged = pyqtSignal()

    ##  Whether or not the model should show all definitions regardless of visibility.
    @pyqtProperty(bool, fset = setShowAll, notify = showAllChanged)
    def showAll(self):
        return self._show_all

    ##  Set the visibilityHandler property
    def setVisibilityHandler(self, visibility_handler):
        if self._visibility_handler:
            self._visibility_handler.visibilityChanged.disconnect(self._onVisibilityChanged)

        self._visibility_handler = visibility_handler

        if self._visibility_handler:
            self._visibility_handler.visibilityChanged.connect(self._onVisibilityChanged)
            self._onVisibilityChanged()

        self.visibilityHandlerChanged.emit()

    ##  Emitted whenever the visibilityHandler property changes
    visibilityHandlerChanged = pyqtSignal()
    ##  An instance of SettingVisibilityHandler to use to determine which settings should be visible.
    @pyqtProperty("QVariant", fset = setVisibilityHandler, notify = visibilityHandlerChanged)
    def visibilityHandler(self):
        return self._visibility_handler

    ##  Set the exclude property
    def setExclude(self, exclude):
        exclude = set(exclude)
        if exclude != self._exclude:
            self._exclude = exclude
            self.excludeChanged.emit()
            self._updateVisibleRows()

    ##  Emitted whenever the exclude property changes
    excludeChanged = pyqtSignal()

    ##  This property indicates which settings should never be visibile.
    @pyqtProperty("QVariantList", fset = setExclude, notify = excludeChanged)
    def exclude(self):
        return list(self._exclude)

    ##  Set the expanded property
    def setExpanded(self, expanded):
        new_expanded = set()
        for item in expanded:
            if item == "*":
                for definition in self._definition_list:
                    if definition.children:
                        new_expanded.add(definition.key)
            else:
                new_expanded.add(str(item))

        if new_expanded != self._expanded:
            self._expanded = new_expanded
            self.expandedChanged.emit()
            self._updateVisibleRows()

    ##  Emitted whenever the exclude property changes
    expandedChanged = pyqtSignal()

    ##  This property indicates which settings should never be visibile.
    @pyqtProperty("QStringList", fset = setExpanded, notify = expandedChanged)
    def expanded(self):
        return list(self._expanded)

    visibleCountChanged = pyqtSignal()
    @pyqtProperty(int, notify = visibleCountChanged)
    def visibleCount(self):
        count = 0
        for index in self._row_index_list:
            definition = self._definition_list[index]
            if definition.key in self._visible:
                count += 1

        return count

    @pyqtProperty(int, notify = visibleCountChanged)
    def categoryCount(self):
        count = 0
        for index in self._row_index_list:
            definition = self._definition_list[index]
            if definition.type == "category":
                count += 1

        return count

    ##  Set the filter of this model based on a string.
    #   \param filter_dict Dictionary to do the filtering by.
    def setFilter(self, filter_dict):
        if filter_dict != self._filter_dict:
            self._filter_dict = filter_dict
            self.filterChanged.emit()
            self._updateVisibleRows()

    filterChanged = pyqtSignal()

    @pyqtProperty("QVariantMap", fset=setFilter, notify=filterChanged)
    def filter(self):
        return self._filter_dict

    ##  Show the children of a specified SettingDefinition.
    @pyqtSlot(str)
    def expand(self, key):
        self._expanded.add(key)
        self.expandedChanged.emit()
        self._updateVisibleRows()

    ##  Show the children of a specified SettingDefinition and all children of those settings as well.
    @pyqtSlot(str)
    def expandAll(self, key):
        if not self._container:
            return

        definitions = self._container.findDefinitions(key = key)
        if not definitions:
            return
        self.expand(key)

        for child in definitions[0].children:
            if child.children:
                self.expandAll(child.key)

    ##  Hide the children of a specified SettingDefinition.
    @pyqtSlot(str)
    def collapse(self, key):
        if not self._container:
            return

        if key not in self._expanded:
            return

        definitions = self._container.findDefinitions(key = key)
        if not definitions:
            return

        self._expanded.remove(key)

        for child in definitions[0].children:
            if child.children:
                self.collapse(child.key)

        self.expandedChanged.emit()
        self._updateVisibleRows()

    ##  Show a single SettingDefinition.
    @pyqtSlot(str)
    def show(self, key):
        self.setVisible(key, True)

    ##  Hide a single SettingDefinition.
    @pyqtSlot(str)
    def hide(self, key):
        self.setVisible(key, False)

    @pyqtSlot(bool)
    def setAllVisible(self, visible):
        new_visible = set()

        for index in self._row_index_list:
            definition = self._definition_list[index]
            if definition.type != "category":
                new_visible.add(self._definition_list[index].key)

        if visible:
            self._visibility_handler.setVisible(new_visible | self._visible)
        else:
            self._visibility_handler.setVisible(self._visible - new_visible)

    ##  Set a single SettingDefinition's visible state
    @pyqtSlot(str, bool)
    def setVisible(self, key, visible):
        if key in self._visible and visible:
            # Ignore already visible settings that need to be made visible.
            return

        if key not in self._visible and not visible:
            # Ignore already hidden settings that need to be hidden.
            return

        definitions = self._container.findDefinitions(key = key)
        if not definitions:
            Logger.log("e", "Tried to change visiblity of a non-existant SettingDefinition")
            return

        if visible:
            self._visible.add(key)
        else:
            self._visible.remove(key)

        if self._visibility_handler:
            self._visibility_handler.setVisible(self._visible)

    @pyqtSlot(str, result = int)
    def getIndex(self, key):
        definitions = self._container.findDefinitions(key = key)
        if not definitions:
            return -1

        index = self._definition_list.index(definitions[0])

        try:
            return self._row_index_list.index(index)
        except ValueError:
            return -1

    @pyqtSlot(str, str, result = "QVariantList")
    def getRequires(self, key, role = None):
        if not self._container:
            return []

        definitions = self._container.findDefinitions(key = key)
        if not definitions:
            return []

        result = []
        for relation in definitions[0].relations:
            if relation.type is not UM.Settings.SettingRelation.RelationType.RequiresTarget:
                continue

            if role and role != relation.role:
                continue

            result.append({ "key": relation.target.key, "label": relation.target.label})

        return result

    @pyqtSlot(str, str, result = "QVariantList")
    def getRequiredBy(self, key, role = None):
        if not self._container:
            return []

        definitions = self._container.findDefinitions(key = key)
        if not definitions:
            return []

        result = []
        for relation in definitions[0].relations:
            if relation.type is not UM.Settings.SettingRelation.RelationType.RequiredByTarget:
                continue

            if role and role != relation.role:
                continue

            result.append({ "key": relation.target.key, "label": relation.target.label})

        return result

    ##  Reimplemented from QAbstractListModel
    def rowCount(self, parent = None):
        if not self._container:
            return 0

        return len(self._row_index_list)

    ##  Reimplemented from QAbstractListModel
    def data(self, index, role):
        if not self._container:
            return QVariant()

        if not index.isValid():
            return QVariant()

        if role not in self._role_names:
            return QVariant()

        try:
            definition = self._definition_list[self._row_index_list[index.row()]]
        except IndexError:
            # Definition is not visible or completely not in the list
            return QVariant()

        if role == self.KeyRole:
            return definition.key
        elif role == self.DepthRole:
            return len(definition.getAncestors())
        elif role == self.VisibleRole:
            return definition.key in self._visible
        elif role == self.ExpandedRole:
            return definition.key in self._expanded

        role_name = self._role_names[role]
        try:
            data = getattr(definition, role_name.decode())
        except AttributeError:
            data = ""

        if isinstance(data, collections.OrderedDict):
            result = []
            for key, value in data.items():
                result.append({"key": key, "value": value})
            return result

        return data

    ##  Reimplemented from QAbstractListModel
    def roleNames(self):
        return self._role_names

    def _onVisibilityChanged(self):
        self._visible = self._visibility_handler.getVisible()

        for row in range(len(self._row_index_list)):
            self.dataChanged.emit(self.index(row, 0), self.index(row, 0), [self.VisibleRole])

        self._updateVisibleRows()

    # Update the internal list of definitions and the visibility mapping.
    #
    # Note that this triggers a model reset and should only be called when the
    # underlying data needs to be updated. Otherwise call _updateVisibleRows.
    def _update(self):
        if not self._container:
            return

        self.beginResetModel()

        self._definition_list.clear()
        self._row_index_list.clear()

        if self._root:
            self._definition_list = self._root.findDefinitions()
        else:
            self._definition_list = self._container.findDefinitions()

        self._updateVisibleRows()

        self.endResetModel()

    # Update the list of visible rows.
    #
    # This will compute the difference between the old state and the new state and
    # insert/remove rows as appropriate.
    def _updateVisibleRows(self):
        currently_visible = set(self._row_index_list) # A set of currently visible items

        new_visible = set() # A new set of visible items
        for index in range(len(self._definition_list)):
            if self._isDefinitionVisible(self._definition_list[index]):
                new_visible.add(index)

        # Calculate the difference between the sets. The items that are in new_visible and
        # not in currently_visible are items that need to be added, the items that are in
        # currently_visible and not in new_visible are items that should be removed.
        to_add = new_visible - currently_visible
        to_remove = currently_visible - new_visible

        # Add the new items. Currently doing this one by one since that proved fast enough.
        for index in sorted(list(to_add)):
            row = self._findRowToInsert(index)
            self.beginInsertRows(QModelIndex(), row, row)
            self._row_index_list.insert(row, index)
            self.endInsertRows()

        # Remove items. Also doing this one by one currently.
        for index in sorted(list(to_remove)):
            row = self._row_index_list.index(index)
            self.beginRemoveRows(QModelIndex(), row, row)
            del self._row_index_list[row]
            self.endRemoveRows()

        self.visibleCountChanged.emit()

    # Helper function to determine if a setting(row) should be visible or not.
    def _isDefinitionVisible(self, definition, **kwargs):
        key = definition.key

        # If it is in the list of things to exclude it is never going to be visible.
        if key in self._exclude:
            return False

        # If any of its ancestors is in the list of things to exclude it also should never be visible.
        if definition.getAncestors() & self._exclude:
            return False

        # If its parent is not expanded we should not show the setting.
        if definition.parent and not definition.parent.key in self._expanded:
            return False

        # If it is not marked as visible we do not have to show it.
        if not self._show_all and key not in self._visible:
            return False

        # If it does not match the current filter, it should not be shown.
        if self._filter_dict and not definition.matchesFilter(**self._filter_dict):
            return False

        # We should not show categories that are empty
        if definition.type == "category":
            if not self._isAnyDescendantVisible(definition):
                return False

        return True

    # Determines if any child of a definition is visible.
    def _isAnyDescendantVisible(self, definition):
        if self._show_all:
            return True

        for child in definition.children:
            if child.key in self._exclude:
                continue

            if self._filter_dict and not child.matchesFilter(**self._filter_dict):
                continue

            if child.key in self._visible:
                return True

            if self._isAnyDescendantVisible(child):
                return True

        return False

    # Find the row where we should insert a certain index.
    def _findRowToInsert(self, index):
        parent = self._definition_list[index].parent
        parent_row = 0
        while parent:
            parent_index = self._definition_list.index(parent)
            try:
                parent_row = self._row_index_list.index(parent_index)
                break
            except ValueError:
                parent = parent.parent

        insert_row = parent_row

        # Since indexes are by definition ordered, we can greatly simplify this bit since we can just assume
        # any setting with an index < the index to insert should come before this index.
        while insert_row < len(self._row_index_list) and self._row_index_list[insert_row] < index:
            insert_row += 1

        return insert_row