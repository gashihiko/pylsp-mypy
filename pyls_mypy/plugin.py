import re
import tempfile
import os
import os.path
import logging
from mypy import api as mypy_api
from pyls import hookimpl
from sys import platform

line_pattern = r"((?:^[a-z]:)?[^:]+):(?:(\d+):)?(?:(\d+):)? (\w+): (.*)"

log = logging.getLogger(__name__)


def parse_line(line, document=None):
    '''
    Return a language-server diagnostic from a line of the Mypy error report;
    optionally, use the whole document to provide more context on it.
    '''
    result = re.match(line_pattern, line)
    if result:
        file_path, lineno, offset, severity, msg = result.groups()

        if file_path != "<string>":  # live mode
            # results from other files can be included, but we cannot return
            # them.
            if document and document.path and not document.path.endswith(
                    file_path):
                log.warning("discarding result for %s against %s", file_path,
                            document.path)
                return None

        lineno = int(lineno or 1) - 1  # 0-based line number
        offset = int(offset or 1) - 1  # 0-based offset
        errno = 2
        if severity == 'error':
            errno = 1
        diag = {
            'source': 'mypy',
            'range': {
                'start': {'line': lineno, 'character': offset},
                # There may be a better solution, but mypy does not provide end
                'end': {'line': lineno, 'character': offset + 1}
            },
            'message': msg,
            'severity': errno
        }
        if document:
            # although mypy does not provide the end of the affected range, we
            # can make a good guess by highlighting the word that Mypy flagged
            word = document.word_at_position(diag['range']['start'])
            if word:
                diag['range']['end']['character'] = (
                    diag['range']['start']['character'] + len(word))

        return diag


@hookimpl
def pyls_lint(config, workspace, document, is_saved):
    settings = config.plugin_settings('pyls_mypy')
    live_mode = settings.get('live_mode', True)
    path = document.path
    loc=path.rfind("\\")
    while (loc)>-1:
        p = path[:loc+1]+"mypy.ini"
        if os.path.isfile(p):
            break
        else:
            path = path[:loc]
    if is_saved:
        args = ['--incremental',
                '--show-column-numbers',
                '--follow-imports', 'silent']
    elif live_mode:
        tmpFile = tempfile.NamedTemporaryFile('w', delete=False)
        tmpFile.write(document.source)
        tmpFile.flush()
        args = ['--incremental',
                '--show-column-numbers',
                '--follow-imports', 'silent',
                '--shadow-file', document.path, tmpFile.name]
    else:
        return []
    if loc != -1:
        args.append('--config-file')
        args.append(p)
    args.append(document.path)
    if settings.get('strict', False):
        args.append('--strict')

    report, errors, _ = mypy_api.run(args)
    if "tmpFile" in locals():
        tmpFile.close()
        os.unlink(tmpFile.name)

    diagnostics = []
    for line in report.splitlines():
        diag = parse_line(line, document)
        if diag:
            diagnostics.append(diag)

    return diagnostics
