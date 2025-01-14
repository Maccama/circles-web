# -*- coding: utf-8 -*-

__all__ = ()

import asyncio
import bcrypt
import hashlib
import aiofiles.os
import os
import time
import markdown2
import requests
import patreon

from cmyui.logging import Ansi
from cmyui.logging import log
from quart import Blueprint
from quart import redirect
from quart import render_template
from quart import request
from quart import session

from PIL import Image
from resizeimage import resizeimage

from constants import regexes
from objects import glob
from objects import utils
from objects.privileges import Privileges
from objects.utils import flash

VALID_MODES = frozenset({'std', 'taiko', 'catch', 'mania'})
VALID_MODS = frozenset({'vn', 'rx', 'ap'})

frontend = Blueprint('frontend', __name__)


@frontend.route('/home')
@frontend.route('/')
async def home():
    return await render_template('home.html')


@frontend.route('/settings')
@frontend.route('/settings/profile')
async def settings_profile():
    if 'authenticated' not in session:
        return await flash('error', 'You must be logged in to access profile settings!', 'login')

    return await render_template('settings/profile.html')


@frontend.route('/settings/profile', methods=['POST'])  # POST
async def settings_profile_post():
    if 'authenticated' not in session:
        return await flash('error', 'You must be logged in to access profile settings!', 'login')

    form = await request.form

    new_name = form.get('username', type=str)
    new_email = form.get('email', type=str)

    if new_name is None or new_email is None:
        return await flash('error', 'Invalid parameters.', 'home')

    old_name = session['user_data']['name']
    old_email = session['user_data']['email']

    # no data has changed; deny post
    if (
            new_name == old_name and
            new_email == old_email
    ):
        return await flash('error', 'No changes have been made.', 'settings/profile')

    if new_name != old_name:
        if not session['user_data']['is_donator'] or session['user_data']['is_staff']:
            return await flash('error', 'Username changes are currently a supporter perk.', 'settings/profile')

        # Usernames must:
        # - be within 2-15 characters in length
        # - not contain both ' ' and '_', one is fine
        # - not be in the config's `disallowed_names` list
        # - not already be taken by another player
        if not regexes.username.match(new_name):
            return await flash('error', 'Your new username syntax is invalid.', 'settings/profile')

        if '_' in new_name and ' ' in new_name:
            return await flash('error', 'Your new username may contain "_" or " ", but not both.', 'settings/profile')

        if new_name in glob.config.disallowed_names:
            return await flash('error', "Your new username isn't allowed; pick another.", 'settings/profile')

        if await glob.db.fetch('SELECT 1 FROM users WHERE name = %s', [new_name]):
            return await flash('error', 'Your new username already taken by another user.', 'settings/profile')

        # username change successful
        await glob.db.execute(
            'UPDATE users '
            'SET name = %s, safe_name = %s '
            'WHERE id = %s',
            [new_name, utils.get_safe_name(new_name),
             session['user_data']['id']]
        )

    if new_email != old_email:
        # Emails must:
        # - match the regex `^[^@\s]{1,200}@[^@\s\.]{1,30}\.[^@\.\s]{1,24}$`
        # - not already be taken by another player
        if not regexes.email.match(new_email):
            return await flash('error', 'Your new email syntax is invalid.', 'settings/profile')

        if await glob.db.fetch('SELECT 1 FROM users WHERE email = %s', [new_email]):
            return await flash('error', 'Your new email already taken by another user.', 'settings/profile')

        # email change successful
        await glob.db.execute(
            'UPDATE users '
            'SET email = %s '
            'WHERE id = %s',
            [new_email, session['user_data']['id']]
        )

    # logout
    session.pop('authenticated', None)
    session.pop('user_data', None)
    return await flash('success', 'Your username/email have been changed! Please login again.', 'login')


@frontend.route('/settings/avatar')
async def settings_avatar():
    if 'authenticated' not in session:
        return await flash('error', 'You must be logged in to access avatar settings!', 'login')

    return await render_template('settings/avatar.html')


@frontend.route('/settings/avatar', methods=['POST'])  # POST
async def settings_avatar_post():
    if 'authenticated' not in session:
        return await flash('error', 'You must be logged in to access avatar settings!', 'login')

    APATH = f'{glob.config.path_to_gulag}.data/avatars'
    EXTENSIONS = [".png", ".jpg", ".jpeg"]

    if session['user_data']['is_donator'] or session['user_data']['is_staff']:
        EXTENSIONS.append(".gif")

    files = await request.files

    avatar_file = (files.get('avatar'))
    ava = (os.path.splitext(avatar_file.filename.lower()))[1]
    avatar_dir = f"{APATH}/{session['user_data']['id']}{ava}"

    if ava not in EXTENSIONS:
        return await flash('error', 'Please submit an image which is either a png, jpg, jpeg! Supporters can use gifs!',
                           'settings/avatar')

    for old_ava in EXTENSIONS:
        old_dir = f"{APATH}/{session['user_data']['id']}{old_ava}"
        if os.path.isfile(old_dir):
            await aiofiles.os.remove(old_dir)

    await avatar_file.save(avatar_dir)
    # img = Image.open(avatar_dir)
    # width, height = img.size
    # if width > 256 or height > 256:
    #    new = resizeimage.resize_cover(img, [256, 256])
    #    new.save(avatar_dir, img.format)

    return await flash('success', 'Your avatar has been successfully changed!', 'settings/avatar')


@frontend.route('/settings/banner')  # GET
async def settings_banner():
    if not 'authenticated' in session:
        return await flash('error', 'You must be logged in to access banner settings!', 'login')

    # Allow only donators and staff to access banner settings.
    # Donators and staff can only change their own banner.

    # donators and staff can change there profile banner.
    if session['user_data']['is_donator'] or session['user_data']['is_staff']:
        # render banner settings page
        return await render_template('settings/banner.html')
    else:
        return await flash('error', 'You must be a donator to change your banner!', 'settings/banner')


@frontend.route('/settings/banner', methods=['POST'])  # POST
async def settings_banner_post():
    if 'authenticated' not in session:
        return await flash('error', 'You must be logged in to access banner settings!', 'login')

    BPATH = f'{glob.config.path_to_gulag}.data/banners'
    EXTENSIONS = [".gif", ".png", ".jpg", ".jpeg"]

    files = await request.files
    banner_file = (files.get('banner'))

    # construct banner file path and extension
    banner = (os.path.splitext(banner_file.filename.lower()))[1]

    banner_dir = f"{BPATH}/{session['user_data']['id']}{banner}"

    if banner not in EXTENSIONS:
        return await flash('error', 'Please submit an image which is either a png, jpg, or gif!', 'settings/banner')

    # remove any old banners
    for old_banner in EXTENSIONS:
        old_dir = f"{BPATH}/{session['user_data']['id']}{old_banner}"
        if os.path.isfile(old_dir):
            await aiofiles.os.remove(old_dir)  # remove old banner

    await banner_file.save(banner_dir)
    # img = Image.open(banner_dir)
    # width, height = img.size
    # if width > 1140 or height > 215:
    #    new = resizeimage.resize_cover(img, [1140, 215])
    #    new.save(banner_dir, img.format)
    return await flash('success', 'Your banner has been successfully changed!', 'settings/banner')


@frontend.route('/settings/password')
async def settings_password():
    if 'authenticated' not in session:
        return await flash('error', 'You must be logged in to access password settings!', 'login')

    return await render_template('settings/password.html')


@frontend.route('/settings/password', methods=["POST"])  # POST
async def settings_password_post():
    if 'authenticated' not in session:
        return await flash('error', 'You must be logged in to access password settings!', 'login')

    form = await request.form
    old_password = form.get('old_password')
    new_password = form.get('new_password')
    repeat_password = form.get('repeat_password')

    # new password and repeat password don't match; deny post
    if new_password != repeat_password:
        return await flash('error', "Your new password doesn't match your repeated password!", 'settings/password')

    # new password and old password match; deny post
    if old_password == new_password:
        return await flash('error', 'Your new password cannot be the same as your old password!', 'settings/password')

    # Passwords must:
    # - be within 8-32 characters in length
    # - have more than 3 unique characters
    # - not be in the config's `disallowed_passwords` list
    if not 8 < len(new_password) <= 32:
        return await flash('error', 'Your new password must be 8-32 characters in length.', 'settings/password')

    if len(set(new_password)) <= 3:
        return await flash('error', 'Your new password must have more than 3 unique characters.', 'settings/password')

    if new_password.lower() in glob.config.disallowed_passwords:
        return await flash('error', 'Your new password was deemed too simple.', 'settings/password')

    # cache and other password related information
    bcrypt_cache = glob.cache['bcrypt']
    pw_bcrypt = (await glob.db.fetch(
        'SELECT pw_bcrypt '
        'FROM users '
        'WHERE id = %s',
        [session['user_data']['id']])
    )['pw_bcrypt'].encode()

    pw_md5 = hashlib.md5(old_password.encode()).hexdigest().encode()

    # check old password against db
    # intentionally slow, will cache to speed up
    if pw_bcrypt in bcrypt_cache:
        if pw_md5 != bcrypt_cache[pw_bcrypt]:  # ~0.1ms
            if glob.config.debug:
                log(f"{session['user_data']['name']}'s change pw failed - pw incorrect.", Ansi.LYELLOW)
            return await flash('error', 'Your old password is incorrect.', 'settings/password')
    else:  # ~200ms
        if not bcrypt.checkpw(pw_md5, pw_bcrypt):
            if glob.config.debug:
                log(f"{session['user_data']['name']}'s change pw failed - pw incorrect.", Ansi.LYELLOW)
            return await flash('error', 'Your old password is incorrect.', 'settings/password')

    # remove old password from cache
    if pw_bcrypt in bcrypt_cache:
        del bcrypt_cache[pw_bcrypt]

    # calculate new md5 & bcrypt pw
    pw_md5 = hashlib.md5(new_password.encode()).hexdigest().encode()
    pw_bcrypt = bcrypt.hashpw(pw_md5, bcrypt.gensalt())

    # update password in cache and db
    bcrypt_cache[pw_bcrypt] = pw_md5
    await glob.db.execute(
        'UPDATE users '
        'SET pw_bcrypt = %s '
        'WHERE safe_name = %s',
        [pw_bcrypt, utils.get_safe_name(session['user_data']['name'])]
    )

    # logout
    session.pop('authenticated', None)
    session.pop('user_data', None)
    return await flash('success', 'Your password has been changed! Please login again.', 'login')


@frontend.route('/u/<id>')
async def profile(id):
    mode = request.args.get('mode', type=str)
    mods = request.args.get('mods', type=str)

    # make sure mode & mods are valid args
    if mode is not None:
        if mode not in VALID_MODES:
            return await render_template('404.html'), 404
    else:
        mode = 'std'

    if mods is not None:
        if mods not in VALID_MODS:
            return await render_template('404.html'), 404
    else:
        mods = 'vn'

    user_data = await glob.db.fetch(
        'SELECT name, id, priv, country '
        'FROM users '
        'WHERE id = %s OR safe_name = %s',
        [id, utils.get_safe_name(id)]
        # ^ allow lookup from both
        #   id and username (safe)
    )

    # user is banned and we're not staff; render 404
    is_staff = 'authenticated' in session and session['user_data']['is_staff']
    if not user_data or not (user_data['priv'] & Privileges.Normal or is_staff):
        return await render_template('404.html'), 404

    return await render_template('profile.html', user=user_data, mode=mode, mods=mods)


@frontend.route('/leaderboard')
@frontend.route('/lb')
async def leaderboard_no_data():
    return await render_template('leaderboard.html', mode='std', sort='pp', mods='vn')


@frontend.route('/leaderboard/<mode>/<sort>/<mods>')
@frontend.route('/lb/<mode>/<sort>/<mods>')
async def leaderboard(mode, sort, mods):
    return await render_template('leaderboard.html', mode=mode, sort=sort, mods=mods)


@frontend.route('/login')
async def login():
    if 'authenticated' in session:
        return await flash('error', "You're already logged in!", 'home')

    return await render_template('login.html')


@frontend.route('/login', methods=['POST'])  # POST
async def login_post():
    if 'authenticated' in session:
        return await flash('error', "You're already logged in!", 'home')

    login_time = time.time_ns() if glob.config.debug else 0

    form = await request.form
    username = form.get('username', type=str)
    passwd_txt = form.get('password', type=str)

    if username is None or passwd_txt is None:
        return await flash('error', 'Invalid parameters.', 'home')

    # check if account exists
    user_info = await glob.db.fetch(
        'SELECT id, name, email, priv, '
        'pw_bcrypt, silence_end '
        'FROM users '
        'WHERE safe_name = %s',
        [utils.get_safe_name(username)]
    )

    # user doesn't exist; deny post
    # NOTE: Bot isn't a user.
    if not user_info or user_info['id'] == 1:
        if glob.config.debug:
            log(f"{username}'s login failed - account doesn't exist.", Ansi.LYELLOW)
        return await flash('error', 'Account does not exist.', 'login')

    # cache and other related password information
    bcrypt_cache = glob.cache['bcrypt']
    pw_bcrypt = user_info['pw_bcrypt'].encode()
    pw_md5 = hashlib.md5(passwd_txt.encode()).hexdigest().encode()

    # check credentials (password) against db
    # intentionally slow, will cache to speed up
    if pw_bcrypt in bcrypt_cache:
        if pw_md5 != bcrypt_cache[pw_bcrypt]:  # ~0.1ms
            if glob.config.debug:
                log(f"{username}'s login failed - pw incorrect.", Ansi.LYELLOW)
            return await flash('error', 'Password is incorrect.', 'login')
    else:  # ~200ms
        if not bcrypt.checkpw(pw_md5, pw_bcrypt):
            if glob.config.debug:
                log(f"{username}'s login failed - pw incorrect.", Ansi.LYELLOW)
            return await flash('error', 'Password is incorrect.', 'login')

        # login successful; cache password for next login
        bcrypt_cache[pw_bcrypt] = pw_md5

    # user not verified; render verify
    if not user_info['priv'] & Privileges.Verified:
        if glob.config.debug:
            log(f"{username}'s login failed - not verified.", Ansi.LYELLOW)
        return await render_template('verify.html')

    # user banned; deny post
    if not user_info['priv'] & Privileges.Normal:
        if glob.config.debug:
            log(f"{username}'s login failed - banned.", Ansi.RED)
        return await flash('error', 'You are banned!', 'login')

    # login successful; store session data
    if glob.config.debug:
        log(f"{username}'s login succeeded.", Ansi.LMAGENTA)

    session['authenticated'] = True
    session['user_data'] = {
        'id': user_info['id'],
        'name': user_info['name'],
        'email': user_info['email'],
        'priv': user_info['priv'],
        'silence_end': user_info['silence_end'],
        'is_staff': user_info['priv'] & Privileges.Staff,
        'is_donator': user_info['priv'] & Privileges.Donator
    }

    if glob.config.debug:
        login_time = (time.time_ns() - login_time) / 1e6
        log(f'Login took {login_time:.2f}ms!', Ansi.LYELLOW)

    return await flash('success', f'Hey, welcome back {username}!', 'home')


@frontend.route('/register')
async def register():
    if 'authenticated' in session:
        return await flash('error', "You're already logged in.", 'home')

    if not glob.config.registration:
        return await flash('error', 'Registrations are currently disabled.', 'home')

    return await render_template('register.html')


@frontend.route('/register', methods=['POST'])  # POST
async def register_post():
    if 'authenticated' in session:
        return await flash('error', "You're already logged in.", 'home')

    if not glob.config.registration:
        return await flash('error', 'Registrations are currently disabled.', 'home')

    form = await request.form
    username = form.get('username', type=str)
    email = form.get('email', type=str)
    passwd_txt = form.get('password', type=str)

    if username is None or email is None or passwd_txt is None:
        return await flash('error', 'Invalid parameters.', 'home')

    if glob.config.hCaptcha_sitekey != 'changeme':
        captcha_data = form.get('h-captcha-response', type=str)
        if (
                captcha_data is None or
                not await utils.validate_captcha(captcha_data)
        ):
            return await flash('error', 'Captcha failed.', 'register')

    # Usernames must:
    # - be within 2-15 characters in length
    # - not contain both ' ' and '_', one is fine
    # - not be in the config's `disallowed_names` list
    # - not already be taken by another player
    # check if username exists
    if not regexes.username.match(username):
        return await flash('error', 'Invalid username syntax.', 'register')

    if '_' in username and ' ' in username:
        return await flash('error', 'Username may contain "_" or " ", but not both.', 'register')

    if username in glob.config.disallowed_names:
        return await flash('error', 'Disallowed username; pick another.', 'register')

    if await glob.db.fetch('SELECT 1 FROM users WHERE name = %s', username):
        return await flash('error', 'Username already taken by another user.', 'register')

    # Emails must:
    # - match the regex `^[^@\s]{1,200}@[^@\s\.]{1,30}\.[^@\.\s]{1,24}$`
    # - not already be taken by another player
    if not regexes.email.match(email):
        return await flash('error', 'Invalid email syntax.', 'register')

    if await glob.db.fetch('SELECT 1 FROM users WHERE email = %s', email):
        return await flash('error', 'Email already taken by another user.', 'register')

    # Passwords must:
    # - be within 8-32 characters in length
    # - have more than 3 unique characters
    # - not be in the config's `disallowed_passwords` list
    if not 8 <= len(passwd_txt) <= 32:
        return await flash('error', 'Password must be 8-32 characters in length.', 'register')

    if len(set(passwd_txt)) <= 3:
        return await flash('error', 'Password must have more than 3 unique characters.', 'register')

    if passwd_txt.lower() in glob.config.disallowed_passwords:
        return await flash('error', 'That password was deemed too simple.', 'register')

    # TODO: add correct locking
    # (start of lock)
    pw_md5 = hashlib.md5(passwd_txt.encode()).hexdigest().encode()
    pw_bcrypt = bcrypt.hashpw(pw_md5, bcrypt.gensalt())
    glob.cache['bcrypt'][pw_bcrypt] = pw_md5  # cache pw

    safe_name = utils.get_safe_name(username)

    # fetch the users' country
    if (
            request.headers and
            (co := request.headers.get('CF-IPCountry', type=str)) is not None
    ):
        country = co
    else:
        country = 'xx'

    async with glob.db.pool.acquire() as conn:
        async with conn.cursor() as db_cursor:
            # add to `users` table.
            await db_cursor.execute(
                'INSERT INTO users '
                '(name, safe_name, email, pw_bcrypt, country, creation_time, latest_activity) '
                'VALUES (%s, %s, %s, %s, %s, UNIX_TIMESTAMP(), UNIX_TIMESTAMP())',
                [username, safe_name, email, pw_bcrypt, country]
            )
            user_id = db_cursor.lastrowid

            # add to `stats` table.
            await db_cursor.executemany(
                'INSERT INTO stats '
                '(id, mode) VALUES (%s, %s)',
                [(user_id, mode) for mode in range(8)]
            )

    if glob.config.debug:
        log(f'{username} has registered - awaiting verification.', Ansi.LMAGENTA)

    # user has successfully registered
    return await render_template('verify.html')


@frontend.route('/logout')
async def logout():
    if 'authenticated' not in session:
        return await flash('error', "You can't logout if you aren't logged in!", 'login')

    if glob.config.debug:
        log(f'{session["user_data"]["name"]} logged out.', Ansi.LMAGENTA)

    # clear session data
    session.pop('authenticated', None)
    session.pop('user_data', None)

    # render login
    return await flash('success', 'Successfully logged out!', 'login')


@frontend.route('/callback/patreon')
async def patreon_callback():
    # return flash as this function is work in progress.
    return await flash('error', 'This feature is a work in progress.', 'home')


@frontend.route('/docs')  # GET
async def docs_no_data():
    docs = []
    async with asyncio.Lock():
        for f in os.listdir('docs/'):
            docs.append(os.path.splitext(f)[0])

    return await render_template('docs.html', docs=docs)


@frontend.route('/doc/<doc>')  # GET
async def docs(doc):
    async with asyncio.Lock():
        markdown = markdown2.markdown_path(f'docs/{doc.lower()}.md')

    return await render_template('doc.html', doc=markdown, doc_title=doc.lower().capitalize())


@frontend.route('/github')
@frontend.route('/gh')
async def github_redirect():
    return redirect(glob.config.github)


@frontend.route('/discord')
async def discord_redirect():
    return redirect(glob.config.discord_server)
