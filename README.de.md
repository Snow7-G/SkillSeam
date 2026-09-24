# SkillSeam

[English](README.md) | [简体中文](README.zh-CN.md) | [日本語](README.ja.md) | [한국어](README.ko.md) | [Español](README.es.md) | **Deutsch**

<p align="center">
  <img src="assets/banner.svg" alt="SkillSeam" width="720">
</p>

Simuliere, wie dein Agent wirklich Skills auswählt, und finde heraus, welcher Skill wessen Aufgaben stiehlt. Bevor deine Nutzer es merken.

## Das Problem

Agent-Runtimes wie Claude Code und Codex laden Skills, indem sie nur ein, zwei Zeilen Description lesen. Kommt eine Aufgabe herein, wählt der Agent den Skill, der am ähnlichsten klingt.

Das funktioniert, solange sich zwei Descriptions nicht überlappen. In unserer Krankenhaus-Demo behauptete die Description eines Buchungs-Skills, dass er auch „Anfragen zu Sehtest-Berichten" bearbeitet. Zuständig war eigentlich der Skill zur Berichtsauswertung. Ein Patient bittet um eine Berichtsauswertung, der Buchungs-Skill antwortet und erfindet dann etwas. Kein Fehler, kein Logeintrag. Wir haben es nur erfahren, weil sich Patienten beschwert haben.

SkillSeam spielt diesen Auswahlprozess vor dem Deployment erneut ab. Beide mitgelieferten Demos sind echte Läufe über 6 Skills und 40 Aufgaben: Das chinesische Set deckt 4 Grenzfälle auf, das englische 6 — alle mit 5/5-Stimmeneinheitlichkeit und ohne wackelige Zeilen. Jeder Konfliktbericht nennt die exakten Schlüsselwörter in der Description des Diebes, die den Diebstahl verursacht haben.

## Schnellstart (Web, keine Installation)

Öffne [https://snow7-g.github.io/SkillSeam/?lang=en](https://snow7-g.github.io/SkillSeam/?lang=en), klicke auf die Demo-Schaltfläche, und nach zehn Sekunden erscheint eine echte Heatmap. Dann eigene Skills einfügen, einen API-Key hinzufügen (er bleibt im Browser, die Anfragen gehen direkt zum Provider) und loslaufen lassen.

Deine Skills liegen als SKILL.md-Dateien vor? Klicke auf der Seite auf die Ordner-Schaltfläche (选择技能文件夹) und wähle das Verzeichnis — die Auswertung läuft im Browser, nichts wird hochgeladen. Oder gib sie in ein paste-fertiges Format aus:

```bash
python3 skill_seam.py export ~/.agents/skills
```

## CLI (lokale Verzeichnisse, CI-Gates)

```bash
git clone https://github.com/Snow7-G/SkillSeam && cd SkillSeam
echo '{"base_url": "https://.../v1", "api_key": "sk-...", "model": "..."}' > .atlasrc.json
python3 skill_seam.py ~/.agents/skills
open output/report.html
```

Exit-Codes: 0 heißt keine Konflikte, 1 heißt Konflikte gefunden, 2 heißt Fehlkonfiguration. Das CI-Gate ist eine Zeile:

```bash
python3 skill_seam.py ./skills --tasks ci-tasks.json
```

## Echte Fragen schlagen generierte

Zuerst eine ehrliche Grenze: Die generierten Testaufgaben sind verzerrt. Das Modell, das sie schreibt, weiß, welcher Skill gewinnen sollte, also fallen sie leicht durch. In unserer Demo fanden generierte Aufgaben 0 Konflikte, echte Nutzerfragen fanden 4. Gleicher Skill-Satz, gleiches Modell.

Deshalb bringt das Tool drei Wege mit, echte Fragen zu sammeln:

```bash
# Einmalige Einrichtung: Jeder Prompt an Claude Code wird lokal und still aufgezeichnet
python3 skill_seam.py capture --install-claude

# In dem Moment, in dem du deinen Agenten bei der falschen Wahl erwischst, bleib es erhalten
python3 skill_seam.py mark "check my membership points at my follow-up visit" followup-reminder

# Aufgezeichnete Prompts (oder Codex-Sitzungslogs) in einen beschrifteten Aufgabenentwurf ernten
python3 skill_seam.py harvest ./skills --codex --label --out tasks-draft.json
```

Entwurf prüfen, erwarteten Skill eintragen, laufen lassen. Zehn echte Vorfälle ergeben ein besseres Aufgabenset als jeder Generator.

Generierte Aufgaben haben trotzdem einen Nutzen: Smoke-Tests. Verlass dich aber nicht darauf, dass Grün die Abwesenheit von Konflikten beweist.

## So funktioniert es

1. Das Skill-Verzeichnis scannen, das Frontmatter jeder SKILL.md parsen und das Format prüfen.
2. Ein Aufgabenset aufbauen: klare Fragen pro Skill, plus absichtlich mehrdeutige an den Grenzen, wo sich zwei Skills überlappen.
3. Die Auswahl nachspielen: Das Modell sieht nur Namen und Descriptions, im Format, wie Agenten sie injizieren, und wählt pro Aufgabe einen Skill. Jede Aufgabe läuft 5-mal bei temperature 0.7.
4. Mit Mehrheitswahl aggregieren. Eine Aufgabe zählt nur als echter Konflikt, wenn mindestens 4 von 5 Läufen demselben falschen Skill zustimmen. Darunter markieren wir sie als instabil, denn das ist Modellrauschen und würde den Bericht verfälschen.

Der Bericht ist eine einzelne, in sich geschlossene HTML-Seite mit einer Confusion-Matrix. Bei Konflikten generiert er auch Description-Umschreibungen (vorher/nachher) zum Anwenden und erneuten Testen.

## Einordnung

| Tool | Was geprüft wird | Umfang |
|---|---|---|
| agnix | Formatregeln (Frontmatter, Namensgebung) | Einzeldatei |
| skilltest | Ob ein Skill allein auslöst | Einzelner Skill |
| SkillSpector (NVIDIA) | Sicherheit: Injection, Exfiltration, Supply Chain | Einzelner Skill |
| **SkillSeam** | Auswahlverhalten nach der Komposition: wer wem Aufgaben stiehlt | Das ganze Skill-Set |

Das ergänzt sich. Lint und Sicherheits-Scans laufen pro Skill, SkillSeam läuft auf dem Set.

## Einschränkungen

Die Simulation ist dem Injektionsformat treu, treibt aber keine echten Agent-Prozesse. Unterschiede zwischen Runtimes (wählt Codex anders als Claude?) stehen auf der Roadmap. Der Codex-Sitzungsparser ist ein toleranter Extraktor, daher können Tool-Ausgaben in die Harvest-Kandidaten rutschen. Das Web-UI spricht derzeit Chinesisch.

## Der Name

Konflikte wohnen nicht in einem Skill. Sie wohnen in der Naht zwischen zwei Skills, wo der Stoff hält, bis jemand zieht. SkillSeam prüft die Nähte.

**Zum Namen.** Es gibt eine unabhängige Arbeit mit demselben Namen: *SkillSeam: Six Principles for Auditing Agent Skill Collections* (Kang Ruiyuan, X32 Studio, [arXiv:2609.13321](https://arxiv.org/abs/2609.13321)), veröffentlicht im September 2026, also vor diesem Projekt. Sie auditiert Skill-Sammlungen mittels kontrollierter Perturbation und liefert einen [installierbaren Skill](https://github.com/X32Studio/best-practice-for-skills-system) mit. Dieses Projekt ist davon unabhängig, ist nicht ihr Messinstrument, und der Name stammt aus der Idee der Naht — die Arbeit war damals nicht bekannt. Wer über die Arbeit hierher kommt, kennt den Namen daher. [Worin sie sich unterscheiden →](research/protocol-alignment.md)


Der Prüfbericht heißt Sirens Report, nach der Lorelei. Heine hat es am besten gesagt:

> Ich weiß nicht, was soll es bedeuten,
> dass ich so traurig bin.
>
> Ein Mägdlein sitzt dort oben, kämmt ihr goldenes Haar und singt. Der Schiffer hört das Lied und sieht die Klippen nicht.

Jede Description singt. Manche Lieder locken deine Aufgaben auf die Klippen.

## Entwicklung

```bash
python3 tests/test_atlas.py   # 98 Tests, nur Stdlib
node tests/web_smoke.cjs      # 103 Web-Assertions, node >= 18
```

CI läuft beides auf Python 3.10, 3.12 und 3.13. Vor einem PR bitte CONTRIBUTING.md lesen.

## Lizenz

MIT
