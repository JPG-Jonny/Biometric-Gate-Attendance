"""Interactive webcam enrollment using an individual staff session."""
import getpass
import os
import requests
from .settings import base_url


def main():
    import cv2
    url = base_url()
    username = input('Administrator username: ').strip()
    password = getpass.getpass('Password (hidden): ')
    try:
        login = requests.post(url + '/api/v1/auth/token', json={'username': username, 'password': password},
                              timeout=(5, 30), allow_redirects=False)
    except requests.RequestException:
        print('Sign-in request failed. Check the API connection.')
        return
    finally:
        password = None
    if login.status_code != 200:
        print('Sign-in failed:', login.status_code)
        return
    token = login.json()['access_token']
    headers = {'Authorization': 'Bearer ' + token}
    try:
        student_id = input('Student ID: ').strip()
        name = input('Full name: ').strip()
        phone = input('Phone (optional): ').strip()
        if input('Informed consent recorded? Type YES: ') != 'YES':
            print('Enrollment cancelled')
            return
        cap = cv2.VideoCapture(int(os.getenv('CAMERA_INDEX', '0')))
        image = None
        try:
            if not cap.isOpened():
                raise RuntimeError('Camera unavailable')
            print('C to capture; Q to cancel')
            while True:
                ok, frame = cap.read()
                if not ok:
                    raise RuntimeError('Camera frame unavailable')
                cv2.imshow('CampusGuard enrollment', frame)
                key = cv2.waitKey(1) & 0xff
                if key == ord('q'):
                    return
                if key == ord('c'):
                    ok, encoded = cv2.imencode('.jpg', frame)
                    if ok:
                        image = encoded.tobytes()
                        break
        finally:
            cap.release()
            cv2.destroyAllWindows()
        response = requests.post(url + '/api/v1/admin/register-student', headers=headers,
            data={'student_id': student_id, 'full_name': name, 'phone_number': phone, 'consent': 'true'},
            files={'file': ('capture.jpg', image, 'image/jpeg')}, timeout=(5, 30), allow_redirects=False)
        print(response.status_code, response.json())
    except requests.RequestException:
        print('Request failed. Check the directory before retrying; the server may have committed.')
    except RuntimeError as error:
        print(str(error))
    finally:
        try:
            requests.post(url + '/api/v1/auth/logout', headers=headers, timeout=(5, 10), allow_redirects=False)
        except requests.RequestException:
            print('Session revocation could not be confirmed. The session will expire automatically.')


if __name__ == '__main__':
    main()
