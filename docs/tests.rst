The tango_ophyd_device repository comes packaged with three test files designed to be run with unittest.
These are

+ test_sim_proxy.py
+ test_example_device.py
+ test_sardana_motor.py

test_sim_proxy.py can be run without any background processes, provided that the bluesky and ophyd.v2 packages are installed. 

test_example_device.py must be run with the exampledevice.py file included in the tango_ophyd_devices repo running in the background.

test_sardana_motor.py must be run with a Sardana instance running in the background, with the sar_demo command having been run inside Sardana's interactive "spock" terminal. 

Each of these conditions is fulfilled by the container included as a package in the repo, and the github/workflows/main.yml workflow runs the tests on this container. 
