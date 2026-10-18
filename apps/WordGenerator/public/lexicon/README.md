# lexicon/

`krdict.json` — words selected and grouped from 국립국어원 「한국어기초사전」
(https://krdict.korean.go.kr, 사전 전체 내려받기 · JSON) by `scripts/build_krdict_lexicon.py`.

The dictionary is distributed under CC BY-SA 2.0 KR
(https://creativecommons.org/licenses/by-sa/2.0/kr/), and so is this file: credit 국립국어원
「한국어기초사전」 when using it, and share anything made from it under the same licence. The app shows
the credit in its footer and in the 단어 사전.

To refresh it from a newer dump: download and unzip the JSON dump into a directory of its own, then
`python3 -I scripts/build_krdict_lexicon.py <that directory>`.
