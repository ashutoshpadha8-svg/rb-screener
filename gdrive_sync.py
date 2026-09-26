#!/usr/bin/env python3
"""
GOOGLE SHEETS SYNC  --  reports as native Google Sheets, same folders as the Mac
===============================================================================

OPTIONAL. Switched on only when ~/Desktop/RB_Screener/google_client_secret.json
exists (the OAuth file you download once from Google Cloud Console).

  push(local.xlsx)  uploads / updates a NATIVE Google Sheet with the same name
                    in My Drive/RB_Screener/<same sub-folders as on the Mac>
  pull(local.xlsx)  if that Google Sheet was edited after the local file
                    (e.g. you picked Actions in Sheets), downloads it back over
                    the local .xlsx -- so rbport / rbtrack see your picks

Permission scope: drive.file = ONLY files this program created. It cannot see
or touch anything else in your Drive.

First use opens the browser once for Google login; the login token is kept in
google_token.json (never printed; delete it to log out). Any Google problem
(no internet, expired login) prints a warning -- the scripts never stop for it.

SETUP (once)
  pip3 install google-api-python-client google-auth-oauthlib
  put google_client_secret.json in ~/Desktop/RB_Screener   (see RB_COMMANDS.md)
  python3 gdrive_sync.py login        -> browser login, then "Google Sheets sync ON"
  python3 gdrive_sync.py status
"""

import os
import sys
import json
import datetime as dt

import daily_screener as ds

ROOT = ds.HERE
SECRET = os.path.join(ROOT, "google_client_secret.json")
TOKEN = os.path.join(ROOT, "google_token.json")
IDS = os.path.join(ds.DATA, "_gdrive_ids.json")      # folder id cache
SCOPES = ["https://www.googleapis.com/auth/drive.file"]
TOP = "RB_Screener"                                  # folder in My Drive
XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
GSHEET = "application/vnd.google-apps.spreadsheet"
FOLDER = "application/vnd.google-apps.folder"

_svc = None
_off_reason = None


def enabled():
    return os.path.exists(SECRET)


def _service(interactive=False):
    """Drive v3 client, or None (with the reason in _off_reason)."""
    global _svc, _off_reason
    if _svc is not None:
        return _svc
    if not enabled():
        _off_reason = "google_client_secret.json not found"
        return None
    try:
        from google.oauth2.credentials import Credentials
        from google.auth.transport.requests import Request
        from google_auth_oauthlib.flow import InstalledAppFlow
        from googleapiclient.discovery import build
    except ImportError:
        _off_reason = ("Google packages missing -- pip3 install "
                       "google-api-python-client google-auth-oauthlib")
        return None
    creds = None
    if os.path.exists(TOKEN):
        try:
            creds = Credentials.from_authorized_user_file(TOKEN, SCOPES)
        except Exception:
            creds = None
    try:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        if not creds or not creds.valid:
            if not interactive:
                _off_reason = "not logged in -- run: python3 gdrive_sync.py login"
                return None
            flow = InstalledAppFlow.from_client_secrets_file(SECRET, SCOPES)
            creds = flow.run_local_server(port=0)
        with open(TOKEN, "w") as f:
            f.write(creds.to_json())
        os.chmod(TOKEN, 0o600)
        _svc = build("drive", "v3", credentials=creds, cache_discovery=False)
        return _svc
    except Exception as e:
        _off_reason = "Google login failed (%s)" % type(e).__name__
        return None


def _load_ids():
    try:
        return json.load(open(IDS))
    except (IOError, OSError, ValueError):
        return {}


def _q(s):
    return s.replace("\\", "\\\\").replace("'", "\\'")


def _find(svc, name, parent, mime):
    q = ("name = '%s' and '%s' in parents and mimeType = '%s' and "
         "trashed = false" % (_q(name), parent, mime))
    r = svc.files().list(q=q, fields="files(id, modifiedTime, webViewLink)",
                         spaces="drive").execute()
    f = r.get("files", [])
    return f[0] if f else None


def _folder_id(svc, parts):
    """My Drive/RB_Screener/<parts...> -- created when missing, ids cached."""
    ids = _load_ids()
    key, parent = "", "root"
    for name in [TOP] + list(parts):
        key = key + "/" + name
        fid = ids.get(key)
        if fid:
            try:
                svc.files().get(fileId=fid, fields="id, trashed").execute()
            except Exception:
                fid = None
        if not fid:
            f = _find(svc, name, parent, FOLDER)
            fid = f["id"] if f else svc.files().create(
                body={"name": name, "mimeType": FOLDER, "parents": [parent]},
                fields="id").execute()["id"]
            ids[key] = fid
        parent = fid
    with open(IDS, "w") as f:
        json.dump(ids, f)
    return parent


def _where(local_path):
    rel = os.path.relpath(os.path.abspath(local_path), ROOT)
    parts = rel.split(os.sep)
    return parts[:-1], os.path.splitext(parts[-1])[0]


def push(local_path, quiet=False):
    """Upload / update the native Google Sheet. Returns its link or None."""
    if not enabled():
        return None
    svc = _service()
    if svc is None:
        if not quiet:
            print("  ! Google Sheets sync skipped: %s" % _off_reason)
        return None
    try:
        from googleapiclient.http import MediaFileUpload
        folders, name = _where(local_path)
        parent = _folder_id(svc, folders)
        media = MediaFileUpload(local_path, mimetype=XLSX, resumable=False)
        old = _find(svc, name, parent, GSHEET)
        if old:
            f = svc.files().update(fileId=old["id"], media_body=media,
                                   fields="id, webViewLink, modifiedTime"
                                   ).execute()
        else:
            f = svc.files().create(body={"name": name, "mimeType": GSHEET,
                                         "parents": [parent]},
                                   media_body=media,
                                   fields="id, webViewLink, modifiedTime"
                                   ).execute()
        link = f.get("webViewLink")
        ids = _load_ids()             # remember OUR upload time, so pull()
        ids["pushed:" + "/".join(folders + [name])] = f.get("modifiedTime", "")
        with open(IDS, "w") as fh:    # only fetches YOUR later edits
            json.dump(ids, fh)
        if not quiet:
            print("  Google Sheet: Drive/%s/%s  %s" % (
                "/".join([TOP] + folders), name, link or ""))
        return link
    except Exception as e:
        if not quiet:
            print("  ! Google Sheets upload failed (%s) -- the .xlsx is fine."
                  % type(e).__name__)
        return None


def pull(local_path, quiet=False):
    """If the Google Sheet was edited after the local file, download it over
    the local .xlsx. Returns True when the local file was replaced."""
    if not enabled():
        return False
    svc = _service()
    if svc is None:
        if not quiet:
            print("  ! Google Sheets sync skipped: %s" % _off_reason)
        return False
    try:
        folders, name = _where(local_path)
        parent = _folder_id(svc, folders)
        f = _find(svc, name, parent, GSHEET)
        if not f:
            return False
        pushed = _load_ids().get("pushed:" + "/".join(folders + [name]), "")
        if pushed:                    # edited in Sheets after our upload?
            if f["modifiedTime"][:19] <= pushed[:19]:
                return False
        else:
            remote = dt.datetime.strptime(f["modifiedTime"][:19],
                                          "%Y-%m-%dT%H:%M:%S").replace(
                tzinfo=dt.timezone.utc).timestamp()
            local = os.path.getmtime(local_path) \
                if os.path.exists(local_path) else 0
            if remote <= local + 5:
                return False
        data = svc.files().export(fileId=f["id"], mimeType=XLSX).execute()
        tmp = local_path + ".dl"
        with open(tmp, "wb") as fh:
            fh.write(data)
        os.replace(tmp, local_path)
        if not quiet:
            print("  took your edits from Google Sheets: %s" % name)
        return True
    except Exception as e:
        if not quiet:
            print("  ! Google Sheets download failed (%s) -- using the local "
                  "file." % type(e).__name__)
        return False


if __name__ == "__main__":
    cmd = (sys.argv[1:] or ["status"])[0]
    if cmd == "login":
        if not enabled():
            sys.exit("Put google_client_secret.json in %s first." % ROOT)
        s = _service(interactive=True)
        print("Google Sheets sync ON" if s else "Login failed: %s" % _off_reason)
    else:
        if not enabled():
            print("Google Sheets sync OFF (no google_client_secret.json).")
        else:
            s = _service()
            print("Google Sheets sync ON" if s else "OFF: %s" % _off_reason)
