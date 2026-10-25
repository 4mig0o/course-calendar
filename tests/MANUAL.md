# Manual acceptance checks

Automated tests use an anonymous synthetic text-layer PDF, a real local HTTP
server and ICS field assertions. They do not certify every school's PDF layout,
real OCR, browser interactions or mobile calendar compatibility.

- Windows: fully extract the ZIP, double-click the launcher in a Chinese path
  with spaces; confirm the browser opens and a PDF can be converted.
- Try launching directly from ZIP or with requirements.txt missing. A clear
  extraction/missing-file hint is desired; currently pip reports a missing file.
- Test missing Python and Python older than 3.11. The current launcher checks
  command availability only, not the minimum version.
- With dependencies installed, disconnect the network and test launch. The
  launcher still invokes pip on every start.
- Test occupied port and slow startup. The current launcher opens the browser
  before the server is ready and does not select an alternate port.
- Browser: disconnect/reconnect the server; verify error wording, recovery and
  successful retry. Refresh an old cached page and inspect the updated wording.
- iOS, Android/Google Calendar and Outlook: import the generated ICS and verify
  event count, Chinese names, dates, local start/end times and all-day end dates.
- Use a locally held real school PDF; compare every preview row with the PDF.
  Do not commit personal PDFs or ICS files to the public repository.

Run automated checks from the project root:

```text
python -m pip install -r requirements-test.txt
python -B -m unittest discover -s tests -v
```

Missing reportlab is a test setup error, not a skipped PDF test. Windows launcher
tests are skipped on other operating systems. Temporary servers are stopped and
temporary files removed by the tests.
