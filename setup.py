#!/usr/bin/env python3
from distutils.core import setup
import subprocess
import glob
import os

subprocess.call(["make"])

ver = os.environ.get("PKGVER") or subprocess.run(['git', 'describe', '--tags'],
      stdout=subprocess.PIPE).stdout.decode().strip()

setup(
  name = 'dispatchsrht',
  packages = [
      'dispatchsrht',
      'dispatchsrht.alembic',
      'dispatchsrht.alembic.versions',
      'dispatchsrht.blueprints',
      'dispatchsrht.tasks',
      'dispatchsrht.tasks.github',
      'dispatchsrht.types',
  ],
  version = ver,
  description = 'dispatch.sr.ht website',
  author = 'Drew DeVault',
  author_email = 'sir@cmpwn.com',
  url = 'https://dispatch.sr.ht/~sircmpwn/dispatch.sr.ht',
  license = 'AGPL-3.0',
  package_data={
      'dispatchsrht': [
          'templates/*.html',
          'templates/github/*.html',
          'static/*',
          'static/icons/*',
      ]
  }
)
