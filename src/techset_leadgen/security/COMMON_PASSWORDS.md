# Common-password list

`common-passwords.txt.gz` is the list behind the password policy's "not a common
password" rule (`crm/security/passwords.py`). It ships with the application, so a
password is checked on the user's computer and is never sent to an online service.

## Contents

- **Source:** the UK National Cyber Security Centre's list of the 100,000 passwords
  seen most often in breach data (derived from Have I Been Pwned's Pwned Passwords),
  as published in the SecLists project:
  `Passwords/Common-Credentials/100k-most-used-passwords-NCSC.txt`
  (<https://github.com/danielmiessler/SecLists>).
- **Retrieved:** 2026-10-23. Source file SHA-256:
  `c2e5696882c603b76bb67a47ee970897e5a76fc4c3f5547abe3d0ca340c576e0` (99,840 lines).
- **Stored form:** 97,745 unique entries, one per line, gzip-compressed (262 KB). Each
  entry is NFKC-normalized, stripped of invisible formatting characters, case-folded, and
  stripped of outer spaces, which is how the policy compares passwords; blank lines and one line of control characters were dropped.
- **Matching:** exact, after the same normalization, which also drops invisible formatting
  characters. `Password123`, `ＰＡＳＳＷＯＲＤ`, and `pass` + zero-width space + `word` match
  `password123` and `password`; variations not on the list (`Password123!`,
  `p@ssw0rd2026`) do not.

## Refreshing it

1. Download the current list (or another one-password-per-line UTF-8 list):

   ```
   curl -fsSL -o ncsc.txt https://raw.githubusercontent.com/danielmiessler/SecLists/master/Passwords/Common-Credentials/100k-most-used-passwords-NCSC.txt
   ```

2. Rebuild the bundled file: `poetry run python scripts/update_common_passwords.py ncsc.txt`.
   The output is reproducible, so an unchanged list produces no diff.
3. Update the retrieval date, checksum, and counts above, and run
   `poetry run pytest tests/crm/test_password_policy.py`.

The Windows build bundles the file through `packaging/TechsetLeadGen.spec`; a test
checks that the spec still lists it.

## Limitations

- It is a fixed snapshot: passwords that became common after the retrieval date are
  not on it until it is refreshed.
- Only exact matches count. Common passwords with a small change (an extra symbol or
  digit, letters swapped for look-alike symbols) pass this rule. Some of them fail the
  similarity or numeric rules, but not all.
- The list reflects mostly English-language breach data; common passwords in other
  languages are under-represented.
- Look-alike letters from other alphabets are not folded: `раssword` written with
  Cyrillic "р" and "а" does not match `password` (that needs Unicode's confusables data,
  which Python does not ship).
- It contains entries shorter than the 8-character minimum. Those fail the length rule
  anyway; they are kept so the error also says the password is common.

## License

SecLists is distributed under the MIT License:

```
MIT License

Copyright (c) 2018 Daniel Miessler

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

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

The underlying password data comes from the NCSC's publication of Have I Been Pwned
data; check their current terms before redistributing a refreshed list.
