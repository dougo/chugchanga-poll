#!/usr/bin/python
import code
import getpass
import sys

sys.path.insert(0, "/usr/local/google_appengine")
sys.path.append("/usr/local/google_appengine/lib/yaml/lib")
sys.path.append("/usr/local/google_appengine/lib/webob")
sys.path.append("/usr/local/google_appengine/lib/django")
sys.path.append("/usr/local/google_appengine/lib/antlr")

print sys.path

from google.appengine.ext.remote_api import remote_api_stub
from google.appengine.ext import db

def auth_func():
    return raw_input('Username:'), getpass.getpass('Password:')

if len(sys.argv) < 2:
    print "Usage: %s app_id [host]" % (sys.argv[0],)
    exit()
app_id = sys.argv[1]
if len(sys.argv) > 2:
    host = sys.argv[2]
else:
    host = '%s.appspot.com' % app_id

remote_api_stub.ConfigureRemoteDatastore(app_id, '/remote_api', auth_func, host)

code.interact('App Engine interactive console for %s' % (app_id,), None, locals())
