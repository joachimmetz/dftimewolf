# -*- coding: utf-8 -*-
"""This class maintains the internal dfTimewolf state.

Use it to track errors, abort on global failures, clean up after modules, etc.
"""

from __future__ import print_function
from __future__ import unicode_literals

import sys
import threading
import traceback

from dftimewolf.lib import errors
from dftimewolf.lib import utils
from dftimewolf.lib.modules import manager as modules_manager


class DFTimewolfState(object):
  """The main State class.

  Attributes:
    config (dftimewolf.config.Config): Class to be used throughout execution.
    errors (list[tuple[str, bool]]): errors generated by a module. These
        should be cleaned up after each module run using the CleanUp() method.
    events (dict[str, threading.Event]): Dictionary to store events signalling
        completion of a given module by name.
    global_errors (list[tuple[str, bool]]): the CleanUp() method moves non
        critical errors to this attribute for later reporting.
    input (list[str]): data that the current module will use as input.
    output (list[str]): data that the current module generates.
    recipe: (dict[str, str]): recipe declaring modules to load.
    store (dict[str, object]): arbitrary data for modules.
  """

  def __init__(self, config):
    """Initializes a state."""
    super(DFTimewolfState, self).__init__()
    self._module_pool = {}
    self._store_lock = threading.Lock()
    self.config = config
    self.errors = []
    self.events = {}
    self.global_errors = []
    self.input = []
    self.output = []
    self.recipe = None
    self.store = {}

  def LoadRecipe(self, recipe):
    """Populates the internal module pool with modules declared in a recipe.

    Args:
      recipe (dict[str, str]): recipe declaring modules to load.

    Raises:
      RecipeParseError: if a module in the recipe does not exist.
    """
    self.recipe = recipe
    for module_description in recipe['modules']:
      # Combine CLI args with args from the recipe description
      module_name = module_description['name']
      module_class = modules_manager.ModulesManager.GetModuleByName(module_name)
      if not module_class:
        raise errors.RecipeParseError(
            'Recipe uses unknown module: {0:s}'.format(module_name))

      self._module_pool[module_name] = module_class(self)

  def StoreContainer(self, container):
    """Thread-safe method to store data in the state's store.

    Args:
      container (AttributeContainer): data to store.
    """
    with self._store_lock:
      self.store.setdefault(container.CONTAINER_TYPE, []).append(container)

  def GetContainers(self, container_class):
    """Thread-safe method to retrieve data from the state's store.

    Args:
      container_class (type): AttributeContainer class used to filter data.

    Returns:
      list[AttributeContainer]: attribute container objects provided in
          the store that correspond to the container type.
    """
    with self._store_lock:
      return self.store.get(container_class.CONTAINER_TYPE, [])

  def SetupModules(self, args):
    """Performs setup tasks for each module in the module pool.

    Threads declared modules' SetUp() functions. Takes CLI arguments into
    account when replacing recipe parameters for each module.

    Args:
      args (list[str]): Command line arguments that will be used to replace
          the parameters declared in the recipe.
    """

    def _SetupModuleThread(module_description):
      """Calls the module's SetUp() function and sets an Event object for it.

      Args:
        module_description (dict): Corresponding recipe module description.
      """
      new_args = utils.ImportArgsFromDict(
          module_description['args'], vars(args), self.config)
      module = self._module_pool[module_description['name']]
      try:
        module.SetUp(**new_args)
      except Exception as exception:  # pylint: disable=broad-except
        self.AddError(
            'An unknown error occurred: {0!s}\nFull traceback:\n{1:s}'.format(
                exception, traceback.format_exc()),
            critical=True)

      self.events[module_description['name']] = threading.Event()
      self.CleanUp()

    threads = []
    for module_description in self.recipe['modules']:
      t = threading.Thread(
          target=_SetupModuleThread,
          args=(module_description, )
      )
      threads.append(t)
      t.start()
    for t in threads:
      t.join()

    self.CheckErrors(is_global=True)

  def RunModules(self):
    """Performs the actual processing for each module in the module pool."""

    def _RunModuleThread(module_description):
      """Runs the module's Process() function.

      Waits for any blockers to have finished before running Process(), then
      sets an Event flag declaring the module has completed.

      Args:
        module_description (str): description of the module.
      """
      for blocker in module_description['wants']:
        self.events[blocker].wait()
      module = self._module_pool[module_description['name']]
      try:
        module.Process()
      except errors.DFTimewolfError as exception:
        self.AddError(exception.message, critical=True)
      except Exception as exception:  # pylint: disable=broad-except
        self.AddError(
            'An unknown error occurred: {0!s}\nFull traceback:\n{1:s}'.format(
                exception, traceback.format_exc()),
            critical=True)
      print('Module {0:s} completed'.format(module_description['name']))
      self.events[module_description['name']].set()
      self.CleanUp()

    threads = []
    for module_description in self.recipe['modules']:
      t = threading.Thread(
          target=_RunModuleThread,
          args=(module_description, )
      )
      threads.append(t)
      t.start()
    for t in threads:
      t.join()

    self.CheckErrors(is_global=True)

  def AddError(self, error, critical=False):
    """Adds an error to the state.

    Args:
      error (str): text that will be added to the error list.
      critical (Optional[bool]): True if dfTimewolf cannot recover from
          the error and should abort.
    """
    self.errors.append((error, critical))

  def CleanUp(self):
    """Cleans up after running a module.

    The state's output becomes the input for the next stage. Any errors are
    moved to the global_errors attribute so that they can be reported at a
    later stage.
    """
    # Move any existing errors to global errors
    self.global_errors.extend(self.errors)
    self.errors = []

    # Make the previous module's output available to the next module
    self.input = self.output
    self.output = []

  def CheckErrors(self, is_global=False):
    """Checks for errors and exits if any of them are critical.

    Args:
      is_global (Optional[bool]): True if the global_errors attribute should
          be checked. False if the error attribute should be checked.
    """
    error_objects = self.global_errors if is_global else self.errors
    if error_objects:
      print('dfTimewolf encountered one or more errors:')
      for error, critical in error_objects:
        print('{0:s}  {1!s}'.format('CRITICAL: ' if critical else '', error))
        if critical:
          print('Critical error found. Aborting.')
          sys.exit(-1)
