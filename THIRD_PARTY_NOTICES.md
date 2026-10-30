# Third-party notices

The project's MIT license is retained in [LICENSE](LICENSE). The following notice
covers incorporated upstream material and must accompany redistribution of that
material. It does not assign third-party ownership to the project author.
See [source distribution scope](docs/history/SOURCE_DISTRIBUTION.md) for the proposed
source-only contents and the separate status of installed dependencies.

## Alembic generic migration template

- Included file: [alembic/script.py.mako](alembic/script.py.mako).
- Upstream project: [Alembic](https://alembic.sqlalchemy.org/),
  [source repository](https://github.com/sqlalchemy/alembic/).
- Upstream file: `alembic/templates/generic/script.py.mako`.
- Comparison baseline: the template and LICENSE packaged with **Alembic 1.20.0**,
  the version pinned in [requirements-foundation.lock](requirements-foundation.lock).
- Applicable license: **MIT**, with the complete supplied notice reproduced below.

The included template is an adaptation of Alembic's generic migration template.
Compared with the 1.20.0 packaged template, it omits the generated Create Date line,
the revision-identifier comment and the upgrade/downgrade docstrings, while
retaining the migration skeleton. This comparison identifies upstream material;
it does not establish the exact version originally used to generate the file.
The attribution update does not alter the included template or its behavior.

Comparison fingerprints (SHA-256):

- Upstream 1.20.0 template: `d38920781b4d31ae1c0a71bc09f41c2ade8feab9e5a087e3f30cb4bbf0c1c9d3`.
- Included template: `48c7bed64c49fdeefd362173fa05715a4d8c250aebd780eb4b41c40791089a45`.
- Upstream license text: `6e68d94a03a0e3e327ddf3e86d1ebedc14eece3922022618fc246a36296fd0cc`.

### Alembic copyright and MIT license

```text
Copyright 2009-2026 Michael Bayer.

Permission is hereby granted, free of charge, to any person obtaining a copy of
this software and associated documentation files (the "Software"), to deal in
the Software without restriction, including without limitation the rights to
use, copy, modify, merge, publish, distribute, sublicense, and/or sell copies
of the Software, and to permit persons to whom the Software is furnished to do
so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
```

The full Alembic distribution is installed separately. This notice applies to its
incorporated template material; dependency declarations do not transfer ownership
or replace the licenses of separately installed packages.
