# -*- coding: utf-8 -*-
"""Report related attribute container definitions."""

from dftimewolf.lib.containers import interface

class Report(interface.AttributeContainer):
  """Analysis report attribute container.
  Attributes:
    module_name (str): name of the module that generated the report.
    text (str): report text.
    attributes (list): attribute list, dicts must contain 'name',
      'type', 'values' keys.
  """
  CONTAINER_TYPE = 'report'

  def __init__(self, module_name, text, attributes=None):
    """Initializes the analysis report.
    Args:
      module_name (str): name of the analysis plugin that generated
          the report.
      text (str): report text.
      attributes (list): attribute list of dicts that must contain 'name',
        'type', 'values' keys.
    """
    super(Report, self).__init__()
    self.module_name = module_name
    self.text = text
    if attributes is None:
      self.attributes = []
    else:
      self.attributes = attributes
