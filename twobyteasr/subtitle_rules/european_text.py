"""Spanish, German, French, Portuguese, Italian and Russian subtitle text rules (2026-10-19).

These languages are written in words separated by spaces, like English, so they
use the English line breaker (english_segmentation) with their own word lists:
which words a line must not end with (articles, prepositions, conjunctions,
auxiliaries, subject pronouns, negations) and which words a break prefers to
come before (conjunctions, relative words). Lengths follow the usual
subtitle guidelines for these languages (Netflix: 42 characters per line,
Russian 39; about 17 characters per second for adults); since 2026-10-21 one
subtitle holds up to two lines, like English.

Unlike English, words may carry accents or be Cyrillic, so the comparable word
core is Unicode-aware, and the cleanup only normalizes spacing: it never
capitalizes a lone "i" (an Italian article) or moves French punctuation spaces.
"""
from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field

from .english_text import EnglishLineRules

_SPACE = re.compile(r"\s+")
_WORD_CORE = re.compile(r"[^\W_]+(?:['’][^\W_]+)*", re.UNICODE)
_NUMBER = re.compile(r"^[$€£¥₽]?\d[\d.,]*(%|k|m)?$", re.IGNORECASE)

LANGUAGES = ("es", "de", "fr", "pt", "it", "ru")
# Chinese names (UI and logs), English names (prompts and models).
LABELS = {"es": "西班牙语", "de": "德语", "fr": "法语", "pt": "葡萄牙语", "it": "意大利语", "ru": "俄语"}
SHORT_LABELS = {"es": "西", "de": "德", "fr": "法", "pt": "葡", "it": "意", "ru": "俄"}
ENGLISH_NAMES = {"es": "Spanish", "de": "German", "fr": "French", "pt": "Portuguese", "it": "Italian",
                 "ru": "Russian"}
NATIVE_NAMES = {"es": "Español", "de": "Deutsch", "fr": "Français", "pt": "Português", "it": "Italiano",
                "ru": "Русский"}
SCENE_TAGS = {"es": "es-ES", "de": "de-DE", "fr": "fr-FR", "pt": "pt-BR", "it": "it-IT", "ru": "ru-RU"}


# Determiners include the number words two to ten (2026-10-19, real Italian clip:
# "fra le due | fessure"): a line never ends on a number waiting for its noun.
@dataclass(frozen=True)
class Lexicon:
    """Word lists of one spaced language for the shared word-based line breaker."""
    code: str
    name: str
    conjunctions: frozenset
    prepositions: frozenset
    determiners: frozenset
    auxiliaries: frozenset
    subjects: frozenset
    negations: frozenset
    unit_words: frozenset = frozenset()
    possessives: frozenset = frozenset()
    # German capitalizes every noun, so a run of capitalized words is no name there.
    names_by_case: bool = True
    # German puts the auxiliary after the participle at a clause end ("geschafft haben"):
    # never break right before it.
    clause_final_auxiliaries: bool = False
    # English "is | not" / French "a | pas": the negation leans on the word before it.
    # Spanish, German, Portuguese, Italian and Russian put it before the verb instead.
    negation_after_verb: bool = False
    rules: EnglishLineRules = field(default_factory=EnglishLineRules)


def _set(text: str) -> frozenset:
    return frozenset(text.split())


LEXICONS = {
    "es": Lexicon(
        "es", "Spanish",
        conjunctions=_set("y e o u pero porque que si cuando mientras aunque pues entonces donde como ni sino "
                          "cual cuales quien quienes ya"),
        prepositions=_set("a de en con por para sin sobre entre hasta desde hacia contra según tras al del"),
        determiners=_set("el la los las un una unos unas este esta estos estas ese esa esos esas aquel aquella "
                         "mi mis tu tus su sus nuestro nuestra nuestros nuestras lo cada otro otra todo toda "
                         "dos tres cuatro cinco seis siete ocho nueve diez"),
        auxiliaries=_set("es son está están estoy estamos era fue ha han he hemos había va voy vamos van puede "
                         "puedo podemos hay ser estar haber tengo tiene tenemos"),
        subjects=_set("yo tú él ella nosotros nosotras ellos ellas usted ustedes vosotros me te se nos le les"),
        negations=_set("no nunca jamás tampoco ni"),
        unit_words=_set("segundos minutos horas días veces puntos niveles monedas vidas")),
    "de": Lexicon(
        "de", "German",
        conjunctions=_set("und oder aber denn weil dass wenn als ob obwohl während bevor nachdem damit sondern "
                          "sowie also dann doch der die das welche welcher welches"),
        prepositions=_set("in an auf aus bei mit nach von vor zu zum zur über unter durch für gegen ohne um bis "
                          "seit zwischen hinter neben im am beim vom ins ans"),
        determiners=_set("der die das den dem des ein eine einen einem einer eines mein meine meinen dein deine "
                         "sein seine ihr ihre unser unsere euer eure dieser diese dieses diesen jeder jede jedes "
                         "kein keine keinen "
                         "zwei drei vier fünf sechs sieben acht neun zehn"),
        auxiliaries=_set("ist sind bin bist war waren wird werden werde hat habe haben hast hatte kann können "
                         "muss müssen will wollen soll sollen darf dürfen mag möchte"),
        subjects=_set("ich du er sie es wir ihr man"),
        negations=_set("nicht nie niemals kein keine"),
        unit_words=_set("sekunden minuten stunden tage mal prozent punkte level münzen leben"),
        names_by_case=False, clause_final_auxiliaries=True),
    "fr": Lexicon(
        "fr", "French",
        conjunctions=_set("et ou mais donc car parce que quand si comme lorsque puisque alors ni qui dont où "
                          "quoique tandis"),
        prepositions=_set("à de en dans sur sous avec pour par sans chez vers entre contre depuis pendant après "
                          "avant au aux du des"),
        determiners=_set("le la les l' un une des du ce cet cette ces mon ma mes ton ta tes son sa ses notre "
                         "nos votre vos leur leurs chaque quel quelle "
                         "deux trois quatre cinq six sept huit neuf dix"),
        auxiliaries=_set("est sont suis es sommes êtes était a ai as avons avez ont avait va vais allons vont "
                         "peut peux pouvons doit dois faut c'est"),
        subjects=_set("je j' tu il elle on nous vous ils elles me te se"),
        negations=_set("ne n' pas plus jamais rien personne"), negation_after_verb=True,
        unit_words=_set("secondes minutes heures jours fois points niveaux pièces vies")),
    "pt": Lexicon(
        "pt", "Portuguese",
        conjunctions=_set("e ou mas porque que se quando enquanto embora pois então onde como nem qual quais quem "
                          "já"),
        prepositions=_set("a de em com por para sem sobre entre até desde contra após no na nos nas do da dos das "
                          "ao à pelo pela num numa"),
        determiners=_set("o a os as um uma uns umas este esta estes estas esse essa esses essas aquele aquela "
                         "meu minha meus minhas teu tua seu sua seus suas nosso nossa cada outro outra todo toda "
                         "dois duas três quatro cinco seis sete oito nove dez"),
        auxiliaries=_set("é são está estão estou estamos era foi tem têm tenho temos vai vou vamos vão pode posso "
                         "podemos há ser estar ter"),
        subjects=_set("eu tu ele ela nós vós eles elas você vocês me te se nos lhe"),
        negations=_set("não nunca jamais nem"),
        unit_words=_set("segundos minutos horas dias vezes pontos níveis moedas vidas")),
    "it": Lexicon(
        "it", "Italian",
        conjunctions=_set("e o ma perché che se quando mentre anche sebbene poiché quindi allora dove come né "
                          "cui quale quali chi"),
        prepositions=_set("a di da in con su per tra fra senza verso contro dopo prima al allo alla ai agli alle "
                          "del dello della dei degli delle nel nello nella nei negli nelle sul sulla dal dalla"),
        determiners=_set("il lo la i gli le un uno una l' questo questa questi queste quel quello quella mio mia "
                         "miei mie tuo tua suo sua nostro nostra ogni altro altra tutto tutta "
                         "due tre quattro cinque sei sette otto nove dieci"),
        auxiliaries=_set("è sono sei siamo era fu ha ho hai abbiamo hanno aveva va vado andiamo vanno può posso "
                         "possiamo c'è essere avere sta sto stiamo"),
        subjects=_set("io tu lui lei noi voi loro mi ti si ci vi gli"),
        negations=_set("non mai niente nessuno né"),
        unit_words=_set("secondi minuti ore giorni volte punti livelli monete vite")),
    "ru": Lexicon(
        "ru", "Russian",
        conjunctions=_set("и а но или что чтобы если когда потому как хотя пока где который которая которые "
                          "которое ни зато либо тоже также"),
        prepositions=_set("в во на с со к ко по о об от до из у за под над при про для без через между перед"),
        determiners=_set("этот эта это эти тот та те мой моя моё мои твой твоя твои его её их наш наша наши ваш "
                         "ваша ваши свой своя свои каждый весь вся всё все какой какая какие "
                         "два две три четыре пять шесть семь восемь девять десять"),
        auxiliaries=_set("был была было были будет буду будем будут есть может могу можем надо нужно хочу хочет "
                         "хотим"),
        subjects=_set("я ты он она оно мы вы они"),
        negations=_set("не ни нет никогда"),
        unit_words=_set("секунд секунды минут минуты часов часа дней раз процентов очков уровней монет жизней"),
        rules=EnglishLineRules(preferred_chars=30, max_chars=39, cue_preferred_chars=56, cue_max_chars=78)),
}


from dataclasses import replace as _replace
from .segmentation_profiles import profile_for as _profile_for
for _code,_lex in list(LEXICONS.items()):
    _p=_profile_for(_code)
    LEXICONS[_code]=_replace(_lex,rules=_replace(_lex.rules,
        preferred_chars=_p.line_preferred,max_chars=_p.line_max,min_chars=_p.minimum_units,max_lines=_p.lines,
        cue_preferred_chars=_p.preferred,cue_max_chars=_p.hard_max,max_seconds=_p.max_seconds,
        min_seconds=_p.min_seconds,comfortable_cps=_p.comfortable_cps,warning_cps=_p.warning_cps,critical_cps=_p.critical_cps))


def lexicon(language: str) -> Lexicon:
    from .segmentation_profiles import profile_for
    profile=profile_for(language)
    if profile.code in LEXICONS:return LEXICONS[profile.code]
    from dataclasses import replace
    return Lexicon(profile.code,profile.name,*([frozenset()]*6),
        rules=replace(EnglishLineRules(),cue_preferred_chars=profile.preferred,
            cue_max_chars=profile.hard_max,max_chars=profile.line_max,max_seconds=profile.max_seconds),
        names_by_case=False)


def normalize_spaces(text: str) -> str:
    """One space between words; punctuation spacing (French 'Quoi ?') is left as recognized."""
    return _SPACE.sub(" ", unicodedata.normalize("NFC", str(text or ""))).strip()


def join(parts) -> str:
    return normalize_spaces(" ".join(str(part or "").strip() for part in parts if str(part or "").strip()))


def words(text: str) -> list[str]:
    return normalize_spaces(text).split(" ") if normalize_spaces(text) else []


def word_core(word: str) -> str:
    """The comparable part of a word: letters (any script), digits and inner apostrophes, lower case."""
    found = _WORD_CORE.search(unicodedata.normalize("NFC", str(word or "")).replace("’", "'"))
    return found.group(0).lower() if found else ""


def display_length(text: str) -> int:
    from .segmentation_profiles import measure
    return int(measure(text,'it'))  # shared grapheme unit; limits remain per lexicon


def clean(text: str) -> str:
    """Spacing only: never changes letters, case, accents or punctuation."""
    return normalize_spaces(text)


def is_number(word: str) -> bool:
    return bool(_NUMBER.match(word_core(word) or word))
