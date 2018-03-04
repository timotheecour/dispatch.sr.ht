#!/usr/bin/env python3
from distutils.core import setup
import subprocess
import glob
import os

subprocess.call(["make"])

ver = os.environ.get("PKGVER") or subprocess.run(['git', 'describe', '--tags'],
      stdout=subprocess.PIPE).stdout.decode().strip()

setup(
  name = 'todosrht',
  packages = [
      'todosrht',
      'todosrht.types',
      'todosrht.blueprints',
      'todosrht.alembic',
      'todosrht.alembic.versions'
  ],
  version = ver,
  description = 'todo.sr.ht website',
  author = 'Drew DeVault',
  author_email = 'sir@cmpwn.com',
  url = 'https://todo.sr.ht/~sircmpwn/todo.sr.ht',
  install_requires = ['srht', 'flask-login', 'alembic'],
  license = 'AGPL-3.0',
  package_data={
      'todosrht': [
          'templates/*.html',
          'static/*',
          'emails/*'
      ]
  }
)
