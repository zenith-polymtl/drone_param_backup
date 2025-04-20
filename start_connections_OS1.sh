mavproxy --master=udpout:192.168.144.12:19856 --out=127.0.0.1:14550 --out=127.0.0.1:14551 --out=127.0.0.1:14552 &
MAVPROXY_PID=$!
echo "MAVProxy started with PID $MAVPROXY_PID"

sleep 2
python3 param_manager.py -c udp:127.0.0.1:14552 -f ofa_ardupilot.param