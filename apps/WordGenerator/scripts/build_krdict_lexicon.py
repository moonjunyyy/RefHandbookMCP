"""Build public/lexicon/krdict.json from the 한국어기초사전 (krdict) JSON dump.

    1. Download it: https://krdict.korean.go.kr → 사전 전체 내려받기 → Json 전체 내려받기 (a zip)
    2. Unzip it into a directory of its own
    3. python3 -I scripts/build_krdict_lexicon.py <that directory> [public/lexicon/krdict.json]

What is taken (lexicalUnit 단어 only; idioms, phrases and affixes are left out):
  - nouns            by semantic category → domain (NOUN_DOMAINS below)
  - adjectives       whose first sense needs only a subject ("1이 차갑다"), as the dictionary's own
                     adnominal form ("차가운"), by category → domain (ADJECTIVE_DOMAINS)
  - verbs            first sense "1이 2를 V" → transitive ("은시계를 숨기다");
                     first sense "1이 V" or "1이 2에서 V", in a category of PLACE_VERB_CATEGORIES → spatial
                     ("골목에서 쓰러지다"). Verbs taking 에 ("1이 2에 V") are left out: the generator would
                     put 에서 before them.
The category tables are the judgement calls: edit them and rerun.

The dictionary is © 국립국어원, CC BY-SA 2.0 KR; so is the file this writes (it says so inside).
Standard library only. Run with -I: the dump is outside data and this reads it, nothing more.
"""
import json
import re
import sys
from pathlib import Path

DOMAINS = ("physical", "character", "spatial", "thematic")

# krdict semantic category → domain, for nouns. A category not listed is left out.
NOUN_DOMAINS = {
    "physical": [
        "주생활 > 생활 용품", "의생활 > 옷 종류", "의생활 > 모자, 신발, 장신구", "의생활 > 옷감", "의생활 > 옷의 부분",
        "식생활 > 음식", "식생활 > 식재료", "식생활 > 음료", "식생활 > 조리 도구", "식생활 > 식사 도구",
        "식생활 > 과일", "식생활 > 곡류", "식생활 > 채소", "삶 > 여가 도구", "삶 > 약품류",
        "사회 생활 > 교통 수단", "사회 생활 > 소통 수단", "사회 생활 > 매체", "경제 생활 > 경제 산물", "교육 > 학습 관련 사물", "종교 > 종교 활동 도구", "정치와 행정 > 무기",
        "자연 > 자원", "자연 > 지표면 사물", "동식물 > 동물류", "동식물 > 곤충류", "동식물 > 식물류",
        "동식물 > 동물의 부분", "동식물 > 식물의 부분",
    ],
    "character": [
        "인간 > 사람의 종류", "인간 > 신체 부위", "인간 > 신체 내부 구성", "인간 > 용모", "인간 > 성격",
        "삶 > 친족 관계", "사회 생활 > 인간관계", "사회 생활 > 직위", "사회 생활 > 직업",
        "경제 생활 > 경제 행위 주체", "교육 > 교수 학습 주체", "종교 > 종교인", "종교 > 신앙 대상",
        "문화 > 문화 활동 주체", "정치와 행정 > 사법 및 치안 주체", "정치와 행정 > 정치 및 행정 주체",
    ],
    "spatial": [
        "자연 > 지형", "자연 > 천체", "주생활 > 주택 구성", "주생활 > 건물 종류", "주생활 > 주거 지역",
        "주생활 > 주거 형태", "삶 > 여가 시설", "삶 > 치료 시설", "식생활 > 식생활 관련 장소",
        "의생활 > 의생활 관련 장소", "사회 생활 > 교통 이용 장소", "사회 생활 > 직장", "경제 생활 > 경제 행위 장소",
        "교육 > 교육 기관", "교육 > 학교 시설", "종교 > 종교 활동 장소", "문화 > 문화 생활 장소",
        "정치와 행정 > 공공 기관",
    ],
    "thematic": [
        "인간 > 감정", "인간 > 태도", "인간 > 감각", "삶 > 삶의 상태", "삶 > 삶의 행위", "삶 > 병과 증상",
        "삶 > 가족 행사", "사회 생활 > 사회 생활 상태", "사회 생활 > 사회 행사", "정치와 행정 > 정치 및 치안 상태",
        "정치와 행정 > 사법 및 치안 행위", "종교 > 종교어", "종교 > 종교 행위", "문화 > 전통 문화", "문화 > 문학",
        "자연 > 재해", "자연 > 기상 및 기후", "경제 생활 > 경제 상태",
    ],
}

# krdict semantic category → domain, for adjectives (as modifiers).
ADJECTIVE_DOMAINS = {
    "physical": ["개념 > 모양", "개념 > 색깔", "개념 > 밝기", "개념 > 온도", "개념 > 속도", "식생활 > 맛",
                 "의생활 > 의복 착용 상태", "주생활 > 주거 상태", "인간 > 감각"],
    "character": ["인간 > 성격", "인간 > 태도", "인간 > 감정", "인간 > 능력", "인간 > 용모", "인간 > 체력 상태"],
    "spatial": ["자연 > 기상 및 기후", "개념 > 위치 및 방향"],
    "thematic": ["삶 > 삶의 상태", "개념 > 성질", "사회 생활 > 사회 생활 상태", "사회 생활 > 인간관계",
                 "경제 생활 > 경제 상태", "정치와 행정 > 정치 및 치안 상태"],
}

# Verbs that read well after "<place>에서" (a subject's own action or happening).
PLACE_VERB_CATEGORIES = {
    "인간 > 신체 행위", "인간 > 생리 현상", "인간 > 소리", "인간 > 신체 변화", "삶 > 삶의 행위", "삶 > 일상 행위",
    "삶 > 여가 활동", "자연 > 기상 및 기후", "자연 > 재해", "자연 > 지형", "동식물 > 동식물 행위",
    "사회 생활 > 교통 이용 행위", "주생활 > 주거 행위",
}

# Object verbs from these categories are left out (counting, pointing, grammar: not story actions).
TRANSITIVE_EXCLUDED_PREFIXES = ("개념 >",)

# Left out of the categories above on purpose: "개념 > 지역" (mostly country and region names) and
# "경제 생활 > 경제 수단" (money as a concept: 융자, 보조금), which read as neither things nor places.

# Nouns in -적 ("평화적") work as modifiers of other nouns, not as things to draw.
NOUN_EXCLUDED = re.compile(r"^.{2,}적$")

HANGUL_WORD = re.compile(r"^[가-힣]+$")


def as_list(x):
    return x if isinstance(x, list) else ([] if x is None else [x])


def feats(node) -> dict:
    out = {}
    for n in as_list(node):
        for f in as_list(n.get("feat") if isinstance(n, dict) else None):
            if isinstance(f, dict) and "att" in f:
                out.setdefault(f["att"], f.get("val", ""))
    return out


def first_frame(entry) -> str:
    """The first sense's argument frame without the headword: "1이 2를", "1이", ""."""
    for s in as_list(entry.get("Sense")):
        p = feats(s).get("syntacticPattern")
        if p:
            return " ".join(p.split()[:-1])
    return ""


def adnominal(entry, lemma: str) -> str | None:
    """The dictionary's own present adnominal form of an adjective ("차가운"): its first conjugated
    form that shares the stem's start and ends in a syllable with ㄴ as its final consonant."""
    stem = lemma[:-1]
    for w in as_list(entry.get("WordForm")):
        f = feats(w)
        form = f.get("writtenForm", "")
        if f.get("type") != "활용" or not HANGUL_WORD.match(form) or not form.startswith(stem[:-1] if len(stem) > 1 else ""):
            continue
        last = ord(form[-1]) - 0xAC00
        if 0 <= last < 11172 and last % 28 == 4:  # ㄴ final
            return form
    return None


def invert(table: dict) -> dict:
    out = {}
    for domain, cats in table.items():
        for c in cats:
            if c in out:
                raise SystemExit(f"category {c!r} is mapped twice")
            out[c] = domain
    return out


def build(dump_dir: Path) -> dict:
    noun_domain, adj_domain = invert(NOUN_DOMAINS), invert(ADJECTIVE_DOMAINS)
    lex = {"modifiers": {d: set() for d in DOMAINS}, "objects": {d: set() for d in DOMAINS},
           "verbs": {"transitive": set(), "spatial": set()}}
    created = ""
    files = sorted(dump_dir.glob("*.json"))
    if not files:
        raise SystemExit(f"{dump_dir}: no .json files (unzip the dump there)")
    for path in files:
        with open(path, encoding="utf-8") as fh:
            data = json.load(fh)
        info = feats(data["LexicalResource"].get("GlobalInformation"))
        created = info.get("creationDate", created)
        for e in data["LexicalResource"]["Lexicon"]["LexicalEntry"]:
            f = feats(e)
            if f.get("lexicalUnit") != "단어":
                continue
            lemma = feats(e.get("Lemma")).get("writtenForm", "")
            if not HANGUL_WORD.match(lemma):
                continue
            pos, cat, frame = f.get("partOfSpeech"), f.get("semanticCategory", ""), first_frame(e)
            if pos == "명사" and cat in noun_domain and len(lemma) >= 2 and not NOUN_EXCLUDED.match(lemma):
                lex["objects"][noun_domain[cat]].add(lemma)
            elif pos == "형용사" and cat in adj_domain and frame == "1이":
                form = adnominal(e, lemma)
                if form:
                    lex["modifiers"][adj_domain[cat]].add(form)
            elif pos == "동사" and lemma.endswith("다"):
                if frame == "1이 2를" and not cat.startswith(TRANSITIVE_EXCLUDED_PREFIXES):
                    lex["verbs"]["transitive"].add(lemma)
                elif frame in ("1이", "1이 2에서") and cat in PLACE_VERB_CATEGORIES:
                    lex["verbs"]["spatial"].add(lemma)
    # a word in two lists keeps its first (the generator's pool would do the same)
    seen, words = set(), {}
    for group in ("objects", "modifiers", "verbs"):
        words[group] = {}
        for key, ws in lex[group].items():
            kept = [w for w in sorted(ws) if w not in seen]
            seen.update(kept)
            words[group][key] = kept
    return {
        "source": "한국어기초사전",
        "publisher": "국립국어원",
        "url": "https://krdict.korean.go.kr",
        "license": "CC BY-SA 2.0 KR",
        "licenseUrl": "https://creativecommons.org/licenses/by-sa/2.0/kr/",
        "dumpCreated": created,
        "note": "Words selected and grouped from the dictionary by scripts/build_krdict_lexicon.py; "
                "this file is distributed under the same license.",
        "words": words,
    }


def main() -> None:
    if len(sys.argv) not in (2, 3):
        raise SystemExit(__doc__)
    out = Path(sys.argv[2] if len(sys.argv) == 3 else "public/lexicon/krdict.json")
    result = build(Path(sys.argv[1]))
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(result, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    counts = {g: {k: len(v) for k, v in ws.items()} for g, ws in result["words"].items()}
    print(f"wrote {out} ({out.stat().st_size // 1024} KB): {json.dumps(counts, ensure_ascii=False)}")


if __name__ == "__main__":
    main()
