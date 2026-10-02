"""Capture once when a face appears; require absence before capturing another event.
No offline access decision is made. Offline captures wait for server verification.
"""
import os
import threading
import time
from datetime import datetime, timezone
from uuid import uuid4
from .offline_sync import Queue
from .settings import terminal_settings


def main():
    import cv2
    import face_recognition
    url, terminal, token, direction = terminal_settings()
    queue = Queue(os.getenv('QUEUE_PATH','data/gate_queue.sqlite3'),os.environ['QUEUE_ENCRYPTION_KEY'],terminal)
    stop = threading.Event()
    messages = ['Ready: '+direction]
    def worker():
        while not stop.is_set():
            try:
                result = queue.flush_once(url,token)
                if result:
                    messages[:] = result[-1:]
            except Exception as exc:
                messages[:] = ['Queue error: '+type(exc).__name__]
            stop.wait(5)
    thread = threading.Thread(target=worker, daemon=True)
    thread.start()
    camera_index = int(os.getenv('CAMERA_INDEX','0'))
    cap = cv2.VideoCapture(camera_index, cv2.CAP_DSHOW) if os.name=='nt' else cv2.VideoCapture(camera_index)
    armed = True
    absent_since = None
    next_check = 0.0
    try:
        if not cap.isOpened():
            raise RuntimeError('Cannot open camera; check CAMERA_INDEX and permissions')
        print('Gate direction:',direction,'| Q or Escape to stop. Offline captures are pending, not verified.')
        while True:
            ok, frame = cap.read()
            if not ok:
                raise RuntimeError('Camera frame unavailable')
            now = time.monotonic()
            if now >= next_check:
                next_check = now + 0.5
                small = cv2.resize(frame,(0,0),fx=.5,fy=.5)
                rgb = cv2.cvtColor(small,cv2.COLOR_BGR2RGB)
                locations = face_recognition.face_locations(rgb)
                if not locations:
                    absent_since = absent_since or now
                    if now-absent_since >= 2:
                        armed=True
                else:
                    absent_since=None
                    if len(locations)>1:
                        messages[:]=['One person at a time']
                    elif armed:
                        encodings=face_recognition.face_encodings(rgb,locations)
                        if len(encodings)==1:
                            queue.enqueue({'event_id':str(uuid4()),'occurred_at':datetime.now(timezone.utc).isoformat(),
                                           'direction':direction,'embedding':encodings[0].tolist()})
                            messages[:]=['Captured; awaiting server verification']
                            armed=False
            cv2.putText(frame,messages[-1][:65],(12,32),cv2.FONT_HERSHEY_SIMPLEX,.55,(0,220,255),1)
            cv2.imshow('CampusGuard '+direction+' | Q to close',frame)
            if cv2.waitKey(1)&0xff in (ord('q'),27):
                break
    finally:
        cap.release();cv2.destroyAllWindows();stop.set();thread.join(timeout=26)

if __name__=='__main__':
    main()
