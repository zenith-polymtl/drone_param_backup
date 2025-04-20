mavproxy --master=udpout:192.168.144.12:19856 --out=127.0.0.1:14550 --out=127.0.0.1:14551 --out=127.0.0.1:14552

sleep 1
python3 param_manager.py -c udp:127.0.0.1:14552 -f OS1_ardupilot.param