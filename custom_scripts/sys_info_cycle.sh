#!/bin/bash 

while true
do
    echo "starting sys_info_extended.py : $(date +"%T")"
    python3 /home/pi/luma.examples/examples/sys_info_extended.py &
    pid1=$!
    sleep 10

    # Here I want to kill sys_info_extended.py
    kill "$pid1"

    echo "starting sys_info.py : $(date +"%T")"
    python3 /home/pi/luma.examples/examples/sys_info.py &
    pid2=$!
    sleep 10

    # Here I want to kill sys_info.py
    kill "$pid2"

    echo "starting sys_histogram.py : $(date +"%T")"
    python3 /home/pi/luma.examples/examples/sys_histogram.py &
    pid3=$!
    sleep 10

    # Here I want to kill sys_histogram.py
    kill "$pid3"
done
