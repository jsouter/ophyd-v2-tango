# type: ignore
from setuptools import setup
setup(name='ophyd_tango_devices',
      version='0.2.0',
      description='Tools to create Tango devices compatible with Ophyd/Bluesky',
      # url = 'https://github.com/jsouter/ophyd-v2-tango',
      author = 'James Souter',
      author_email=  'james.souter@diamond.ac.uk',
      packages = ['src/ophyd_tango_devices'],
      install_requires = ['ophyd', 'bluesky'])
    #   install_requires = ['ophyd', 'bluesky', 'tango'])
