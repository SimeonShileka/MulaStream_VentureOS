"""Create an initial administrator offline. Run from your existing project folder."""
import getpass
from app import conn, ph, now

email=input('Administrator email: ').strip().lower()
name=input('Administrator display name: ').strip()
password=getpass.getpass('New administrator password (16+ characters): ')
if len(password)<16 or len(name)<2 or '@' not in email:
    raise SystemExit('Invalid administrator name, email or password')
with conn() as c:
    user=c.execute('SELECT id FROM users WHERE email=?',(email,)).fetchone()
    if user:
        raise SystemExit('Email already registered. Use a new admin email; no existing roles were changed.')
    cursor=c.execute('INSERT INTO users(name,email,password_hash,role,created_at) VALUES(?,?,?,?,?)',
                     (name,email,ph.hash(password),'investor',now()))
    c.execute('INSERT INTO admin_accounts(user_id) VALUES(?)',(cursor.lastrowid,))
print('Administrator created. Log in on the usual sign-in page.')
