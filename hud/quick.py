"""Instant voice commands for the HUD: recognised with rules, no model call.

Common commands (timers, volume, music, open app/site, YouTube, time, date,
screenshot, lock, notes, stop/repeat, language and speed) are matched here and
answered in ~0.1 s. Anything not matched confidently returns None and goes to
the model. Bangla, Banglish and English are supported, including English app
names that Bangla speech recognition writes in Bangla script.
"""

from __future__ import annotations

import re
import unicodedata
from datetime import datetime
from typing import Callable, Optional

BN_DIGITS = "০১২৩৪৫৬৭৮৯"
TO_ASCII = str.maketrans(BN_DIGITS, "0123456789")
TO_BN = str.maketrans("0123456789", BN_DIGITS)


def nfc(s: str) -> str:
    return unicodedata.normalize("NFC", s)


def bn_num(n) -> str:
    return str(n).translate(TO_BN)


# --------------------------------------------------------------------------- language

BANGLISH = set("""ami amar amake tumi tomar apni apnar koro kore korbo kholo khulo chalao chalu bajao lagao
dao daw bolo bolte ache ase achhe nai nei ki keno kemon koto koyta kotota baje kal aj ajke porshu ekhon
komao barao kombe ektu onek gaan gan thamao thamo bondho chup abar aste taratari hobe dekhao dekhaw shono
rakho mone tarikh bar somoy shomoy ghonta minit""".split())


def wants_bangla(text: str) -> bool:
    if re.search(r"[ঀ-৿]", text):
        return True
    words = set(re.findall(r"[a-z]+", text.lower()))
    return len(words & BANGLISH) >= 1


# --------------------------------------------------------------------------- aliases
# Bangla speech recognition writes English names in Bangla script.
ALIASES = {nfc(k): v for k, v in {
    "ইউটিউব": "youtube", "ইউটুব": "youtube", "গুগল": "google", "জিমেইল": "gmail", "জি মেইল": "gmail",
    "ফেসবুক": "facebook", "মেসেঞ্জার": "messenger", "হোয়াটসঅ্যাপ": "whatsapp", "হোয়াটস অ্যাপ": "whatsapp",
    "গিটহাব": "github", "গিট হাব": "github", "চ্যাটজিপিটি": "chatgpt", "চ্যাট জিপিটি": "chatgpt", "ক্লড": "claude",
    "লিংকডইন": "linkedin", "লিঙ্কডইন": "linkedin", "ইনস্টাগ্রাম": "instagram", "নেটফ্লিক্স": "netflix",
    "গুগল ম্যাপ": "maps", "ম্যাপ": "maps", "গুগল ড্রাইভ": "drive", "ড্রাইভ": "drive", "প্রথম আলো": "prothom alo",
    "নোটপ্যাড": "notepad", "নোট প্যাড": "notepad", "ক্যালকুলেটর": "calculator", "ক্যালকুলেটার": "calculator",
    "পেইন্ট": "paint", "টাস্ক ম্যানেজার": "task manager", "ফাইল এক্সপ্লোরার": "file explorer",
    "এক্সপ্লোরার": "file explorer", "সেটিংস": "settings", "সেটিং": "settings", "ক্যামেরা": "camera",
    "এজ": "edge", "ক্রোম": "chrome", "গুগল ক্রোম": "chrome", "ভিএস কোড": "vs code", "ভি এস কোড": "vs code",
    "স্পটিফাই": "spotify", "ওয়ার্ড": "word", "এক্সেল": "excel", "পাওয়ারপয়েন্ট": "powerpoint",
    "পাওয়ার পয়েন্ট": "powerpoint", "স্নিপিং টুল": "snipping tool", "ডাউনলোড": "downloads", "ডাউনলোডস": "downloads",
    "ডকুমেন্ট": "documents", "ডকুমেন্টস": "documents", "ডেস্কটপ": "desktop", "ছবি": "pictures",
    "পিকচার": "pictures", "পিকচারস": "pictures", "ভিডিও": "videos", "ভিডিওস": "videos", "মিউজিক": "music",
    "জার্ভিস ফোল্ডার": "jarvis folder", "ক্যালেন্ডার": "calendar", "ঘড়ি": "clock",
    "calculater": "calculator", "calcutator": "calculator", "note pad": "notepad", "v s code": "vs code",
    "visual studio": "vs code", "download": "downloads", "document": "documents", "picture": "pictures",
    "video": "videos", "you tube": "youtube", "what's app": "whatsapp", "whats app": "whatsapp", "g mail": "gmail",
    "git hub": "github", "chat gpt": "chatgpt", "file manager": "file explorer", "this pc": "file explorer",
}.items()}

FILLER = r"(?:ta|টা|ti|টি|টাকে|take|ke|কে|e|এ|te|তে|folder|ফোল্ডার|app|অ্যাপ|এপ|application|website|ওয়েবসাইট|site|সাইট|the|a|my|amar|আমার|please|plz|প্লিজ)"


def canonical(name: str, norm: Callable[[str], str]) -> str:
    """Map a spoken app/site name to its canonical key (English)."""
    t = norm(name)
    t = re.sub(rf"^(?:{FILLER}\s+)+|(?:\s+{FILLER})+$", "", t).strip()
    return ALIASES.get(t, t)


# --------------------------------------------------------------------------- numbers & durations

NUM_WORDS = {nfc(k): v for k, v in {
    "এক": 1, "দুই": 2, "দু": 2, "তিন": 3, "চার": 4, "পাঁচ": 5, "ছয়": 6, "ছয়": 6, "সাত": 7, "আট": 8, "নয়": 9,
    "নয়": 9, "দশ": 10, "বারো": 12, "পনেরো": 15, "পনের": 15, "বিশ": 20, "কুড়ি": 20, "পঁচিশ": 25, "ত্রিশ": 30,
    "তিরিশ": 30, "চল্লিশ": 40, "পঁয়তাল্লিশ": 45, "পঞ্চাশ": 50, "ষাট": 60,
    "ek": 1, "dui": 2, "tin": 3, "char": 4, "pach": 5, "paach": 5, "panch": 5, "choy": 6, "saat": 7, "aat": 8,
    "noy": 9, "dosh": 10, "das": 10, "baro": 12, "ponero": 15, "bish": 20, "pochish": 25, "tirish": 30,
    "chollish": 40, "ponchash": 50, "shat": 60,
    "one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7, "eight": 8, "nine": 9,
    "ten": 10, "twelve": 12, "fifteen": 15, "twenty": 20, "thirty": 30, "forty": 40, "forty five": 45,
    "fifty": 50, "sixty": 60, "a": 1, "an": 1,
}.items()}

UNIT = {"s": 1, "m": 60, "h": 3600}
UNIT_RE = (r"(?P<u>sec(?:ond)?s?|সেকেন্ড\w*|min(?:ute)?s?|minit|মিনিট\w*|hours?|hr|ghon?ta|ghanta|"
           r"ঘণ্টা\w*|ঘন্টা\w*)")


def _unit(u: str) -> int:
    if u.startswith(("sec", "সেকেন্ড")):
        return UNIT["s"]
    if u.startswith(("min", "মিনিট")):
        return UNIT["m"]
    return UNIT["h"]


def duration_seconds(text: str) -> int:
    t = text.translate(TO_ASCII)
    total = 0.0
    if re.search(r"আধা ঘণ্টা|আধ ঘণ্টা|আধা ঘন্টা|adha gh|half an hour|half hour", t):
        total += 1800
    if re.search(r"দেড় ঘণ্টা|দেড় ঘন্টা|der gh|one and a half hour", t):
        total += 5400
    words = "|".join(sorted(map(re.escape, NUM_WORDS), key=len, reverse=True))
    for m in re.finditer(rf"(?<![\wঀ-৿])(?P<n>\d+(?:\.\d+)?|{words})\s*{UNIT_RE}", t):
        n = m.group("n")
        total += (float(n) if n[0].isdigit() else NUM_WORDS[n]) * _unit(m.group("u"))
    return int(total)


TIMER_LABELS = {nfc(k): v for k, v in {
    "চা": "চা", "চায়ের": "চা", "cha": "Tea", "chaa": "Tea", "tea": "Tea", "ভাত": "ভাত", "bhat": "Rice",
    "rice": "Rice", "পড়া": "পড়া", "পড়ার": "পড়া", "pora": "Study", "porar": "Study", "study": "Study",
    "break": "Break", "বিরতি": "বিরতি", "nap": "Nap", "ঘুম": "ঘুম", "ghum": "Nap", "namaz": "Namaz",
    "নামাজ": "নামাজ", "নামাজের": "নামাজ", "রান্না": "রান্না", "ranna": "Cooking", "cooking": "Cooking",
    "focus": "Focus", "pomodoro": "Focus", "workout": "Workout", "exercise": "Workout", "ব্যায়াম": "ব্যায়াম",
}.items()}


# --------------------------------------------------------------------------- replies

BN_MONTHS = ["জানুয়ারি", "ফেব্রুয়ারি", "মার্চ", "এপ্রিল", "মে", "জুন", "জুলাই", "আগস্ট", "সেপ্টেম্বর", "অক্টোবর",
             "নভেম্বর", "ডিসেম্বর"]
BN_DAYS = ["সোমবার", "মঙ্গলবার", "বুধবার", "বৃহস্পতিবার", "শুক্রবার", "শনিবার", "রবিবার"]


def bn_period(h: int) -> str:
    return "ভোর" if 4 <= h < 6 else "সকাল" if h < 12 and h >= 6 else "দুপুর" if 12 <= h < 15 else \
        "বিকাল" if 15 <= h < 18 else "সন্ধ্যা" if 18 <= h < 20 else "রাত"


def bn_time(h: int, m: int) -> str:
    h12 = h % 12 or 12
    return f"{bn_period(h)} {bn_num(h12)}টা" + (f" {bn_num(m)} মিনিট" if m else "")


def bn_date(iso: str) -> str:
    d = datetime.strptime(iso, "%Y-%m-%d")
    return f"{bn_num(d.day)} {BN_MONTHS[d.month - 1]}"


def say_duration(sec: int, bn: bool) -> str:
    h, m, s = sec // 3600, sec // 60 % 60, sec % 60
    if bn:
        parts = [f"{bn_num(h)} ঘণ্টা" if h else "", f"{bn_num(m)} মিনিট" if m else "", f"{bn_num(s)} সেকেন্ড" if s else ""]
    else:
        parts = [f"{h} hour{'s' * (h != 1)}" if h else "", f"{m} minute{'s' * (m != 1)}" if m else "",
                 f"{s} second{'s' * (s != 1)}" if s else ""]
    return " ".join(p for p in parts if p)


MEDIA_SAY = {
    "volume_up": ("ভলিউম বাড়ালাম।", "Volume up."), "volume_down": ("ভলিউম কমালাম।", "Volume down."),
    "mute": ("মিউট করলাম।", "Muted."), "play_pause": ("ঠিক আছে।", "Done."),
    "next": ("পরেরটা চালাচ্ছি।", "Skipping to the next one."), "previous": ("আগেরটা চালাচ্ছি।", "Going back."),
}


def confirm(tool: str, args: dict, result: str, bn: bool) -> Optional[str]:
    """Short spoken confirmation for a tool that just ran, or None if the
    result needs the model to explain it (errors, lookups, Jarvis tasks)."""
    if re.match(r"(Error|No |Unknown|Refused|Task \w+ \(|Approval)", result) or "is not in my quick-open list" in result:
        return None
    a = args or {}
    match tool:
        case "set_timer":
            m = re.search(r"set for (\d+) min (\d+) s", result)
            sec = int(m.group(1)) * 60 + int(m.group(2)) if m else 0
            label = a.get("label") or ""
            return (f"{label + ' ' if label else ''}টাইমার {say_duration(sec, True)}-এর জন্য চালু করলাম।" if bn
                    else f"{label + ' ' if label else ''}timer set for {say_duration(sec, False)}.".capitalize())
        case "cancel_timer":
            return "টাইমার বন্ধ করলাম।" if bn else "Timer cancelled."
        case "add_note":
            return "নোট রেখে দিলাম।" if bn else "Noted."
        case "delete_note":
            return "নোটটা মুছে দিলাম।" if bn else "Note deleted."
        case "add_todo":
            return f"টু-ডু লিস্টে যোগ করলাম: {a.get('title', '')}।" if bn else f"Added to your to-do list: {a.get('title', '')}."
        case "complete_todo":
            return "শেষ হিসেবে চিহ্নিত করলাম।" if bn else "Marked as done."
        case "delete_todo":
            return "টু-ডু মুছে দিলাম।" if bn else "To-do deleted."
        case "add_event":
            date, time = a.get("date", ""), a.get("time", "")
            try:
                when_bn = bn_date(date) + (f", {bn_time(*map(int, time.split(':')))}" if time else "")
                when_en = datetime.strptime(date, "%Y-%m-%d").strftime("%d %B").lstrip("0") + (f" at {time}" if time else "")
            except ValueError:
                when_bn = when_en = f"{date} {time}".strip()
            return (f"ক্যালেন্ডারে রাখলাম: {a.get('title', '')}, {when_bn}।" if bn
                    else f"Added to your calendar: {a.get('title', '')}, {when_en}.")
        case "delete_event":
            return "ইভেন্টটা মুছে দিলাম।" if bn else "Event deleted."
        case "open_app" | "open_website":
            return "খুলছি।" if bn else "Opening it."
        case "play_youtube":
            return "ইউটিউবে খুঁজে দিলাম, পছন্দের ভিডিওতে ক্লিক করুন।" if bn else "Here it is on YouTube — pick the video you want."
        case "media_control":
            action = re.search(r"Done: (.+)\.", result)
            key = (action.group(1).replace(" ", "_") if action else "")
            return MEDIA_SAY.get(key, ("ঠিক আছে।", "Done."))[0 if bn else 1]
        case "lock_pc":
            return "পিসি লক করছি।" if bn else "Locking the PC."
        case "take_screenshot":
            return "স্ক্রিনশট নিলাম, Pictures-এর Screenshots ফোল্ডারে আছে।" if bn else "Screenshot saved in Pictures, Screenshots."
        case "get_weather":  # already a spoken sentence; only use it if the language matches
            return result if bn == bool(re.search(r"[ঀ-৿]", result)) else None
        case "get_news":
            heads = [re.sub(r"\s*\([^()]*\)$", "", line.split(". ", 1)[-1]) for line in result.splitlines() if line.strip()]
            topic = (a.get("topic") or "").strip()
            if bn:
                intro = f"{topic} নিয়ে সর্বশেষ খবর।" if topic else "আজকের শীর্ষ খবর।"
                return intro + " " + " ".join(f"{bn_num(i)}. {h.rstrip('।.')}।" for i, h in enumerate(heads, 1))
            intro = f"Latest news on {topic}." if topic else "Here are the top headlines."
            return intro + " " + " ".join(f"{i}. {h.rstrip('.')}." for i, h in enumerate(heads, 1))
    return None


NEWS_WORDS = r"(news|খবর|খবরগুলো|নিউজ|নিউজগুলো|khobor|khobor gulo|headline|headlines|শিরোনাম)"
NEWS_FILLER = set(nfc(w) for w in """news খবর খবরগুলো নিউজ নিউজগুলো khobor headline headlines শিরোনাম ajker আজকের today today s
todays top টপ latest সর্বশেষ শীর্ষ বড় boro main প্রধান important গুরুত্বপূর্ণ bangladesh বাংলাদেশের বাংলাদেশ
bangladesher desher দেশের amake আমাকে amar আমার shunao শোনাও শুনাও sonao poro পড়ো pore পড়ে পরে dao দাও din দিন
den দেন bolo বলো বলেন ki কি কী ache আছে the me tell read give what are s whats show dekhao দেখাও koro করো ekhon
এখন ektu একটু please প্লিজ ta টা gulo গুলো guli গুলি er এর r and ar আর a some kichu কিছু jarvis জার্ভিস
on about niye নিয়ে sombondhe সম্পর্কে""".split())


def news_request(w: str) -> Optional[dict]:
    if not re.search(NEWS_WORDS, w):
        return None
    rest = [t for t in w.split() if t not in NEWS_FILLER]
    if len(rest) > 4:
        return None
    return {"tool": "get_news", "args": {"topic": " ".join(rest)}}


WEATHER_WORDS = r"(weather|আবহাওয়া|আবহাওয়ার|আবহাওয়া|আবহাওয়ার|abohawa|abhawa|তাপমাত্রা|temperature|tapmatra|forecast)"
WEATHER_FILLER = set(nfc(w) for w in """weather আবহাওয়া আবহাওয়ার আবহাওয়া আবহাওয়ার abohawa abhawa তাপমাত্রা temperature tapmatra
forecast কেমন kemon ki কি কী how how s hows what what s whats is the in at of for today ajke ajker আজ আজকের এখন ekhon
now current বলো bolo জানাও janao দাও dao দিন din বলেন বলুন tell me amake আমাকে report রিপোর্ট খবর khobor news
অবস্থা obostha koto কত ache আছে jarvis জার্ভিস please প্লিজ e এ te তে er এর r""".split())


def weather_request(w: str, bn: bool) -> Optional[dict]:
    if not re.search(WEATHER_WORDS, w):
        return None
    rest = [t for t in w.split() if t not in WEATHER_FILLER]
    if len(rest) > 3:
        return None
    return {"tool": "get_weather", "args": {"city": " ".join(rest), "language": "bn" if bn else "en"}}


DIRECT_TOOLS = {"get_news", "get_weather", "set_timer", "cancel_timer", "add_note", "delete_note", "add_todo", "complete_todo", "delete_todo",
                "add_event", "delete_event", "open_app", "open_website", "play_youtube", "media_control",
                "lock_pc", "take_screenshot"}


# --------------------------------------------------------------------------- intent matching


def _short(words: str, n: int = 7) -> bool:
    return len(words.split()) <= n


def match(text: str, norm: Callable[[str], str], history: list[dict]) -> Optional[dict]:
    """Return {"tool": name, "args": {...}} or {"reply": ..., "client": {...}} or None."""
    w = norm(nfc(text))
    if not w:
        return None

    # stop / repeat / language / speed (handled in the page)
    if re.fullmatch(r"(stop|stop it|thamo|thamen|chup|chup koro|enough|shut up|be quiet|থামো|থামেন|থাম|চুপ|চুপ করো|"
                    r"যথেষ্ট|আর বলতে হবে না|ar bolte hobe na)( jarvis| জার্ভিস)?", w):
        return {"reply": "", "client": {"stop_speaking": True}}
    if re.fullmatch(r"(abar bolo|abar bolen|repeat|repeat that|say that again|ki bolle|ki bolla|আবার বলো|আবার বলেন|"
                    r"কি বললে|কী বললে|আরেকবার বলো)( please| প্লিজ)?", w):
        last = next((m["content"] for m in reversed(history[:-1]) if m["role"] == "assistant"), "")
        return {"reply": last or ("আমি এখনো কিছু বলিনি।" if wants_bangla(text) else "I haven't said anything yet.")}
    if re.search(r"(english e|ইংরেজিতে|ইংলিশে|in english|speak english|english mode)", w) and _short(w, 6):
        return {"reply": "Okay, I'll listen in English now.", "client": {"lang": "en-US"}}
    if re.search(r"(banglay|bangla te|বাংলায়|বাংলাতে|in bangla|in bengali|bangla mode)", w) and _short(w, 6):
        return {"reply": "ঠিক আছে, এখন থেকে বাংলায় শুনব।", "client": {"lang": "bn-BD"}}
    if re.search(r"(aste bolo|আস্তে বলো|ধীরে বলো|slow down|speak slower|slower)", w) and _short(w, 5):
        return {"reply": "ঠিক আছে, আস্তে বলছি।" if wants_bangla(text) else "Okay, slower.", "client": {"rate": -0.15}}
    if re.search(r"(taratari bolo|তাড়াতাড়ি বলো|দ্রুত বলো|speak faster|faster)", w) and _short(w, 5):
        return {"reply": "ঠিক আছে, তাড়াতাড়ি বলছি।" if wants_bangla(text) else "Okay, faster.", "client": {"rate": 0.15}}

    bn = wants_bangla(text)

    # time & date
    if re.search(r"(koyta baje|kota baje|কয়টা বাজে|কটা বাজে|কয়টা বাজে|what time|what's the time|time koto|"
                 r"সময় কত|somoy koto|shomoy koto)", w) and _short(w, 8):
        now = datetime.now()
        return {"reply": f"এখন {bn_time(now.hour, now.minute)}।" if bn else f"It's {now:%I:%M %p}.".replace(" 0", " ")}
    if re.search(r"(koto tarikh|কত তারিখ|ki bar|কি বার|কী বার|what.?s the date|what day|today.?s date|ajke ki bar)",
                 w) and _short(w, 8):
        now = datetime.now()
        return {"reply": (f"আজ {BN_DAYS[now.weekday()]}, {bn_date(now.strftime('%Y-%m-%d'))} {bn_num(now.year)}।" if bn
                          else f"Today is {now:%A, %d %B %Y}.")}

    # timers
    if re.search(r"(timer|টাইমার|alarm|অ্যালার্ম|এলার্ম|এলার্ম)", w):
        if re.search(r"(cancel|bondho|বন্ধ|বাতিল|off|stop|remove|মুছে|delete|batil)", w):
            return {"tool": "cancel_timer", "args": {}}
        sec = duration_seconds(w)
        if 0 < sec <= 24 * 3600:
            label = next((TIMER_LABELS[t] for t in w.split() if t in TIMER_LABELS), "")
            return {"tool": "set_timer", "args": {"seconds": str(sec), "label": label}}

    # screenshot / lock
    if re.search(r"(screenshot|screen shot|স্ক্রিনশট|স্ক্রিন শট)", w) and _short(w, 6):
        return {"tool": "take_screenshot", "args": {}}
    if re.fullmatch(r"((pc|computer|laptop|screen|পিসি|কম্পিউটার|ল্যাপটপ|স্ক্রিন)( ta| টা)? )?(lock|লক)( koro| করো| kore dao| করে দাও| it)?|"
                    r"lock (the )?(pc|computer|screen|laptop)", w):
        return {"tool": "lock_pc", "args": {}}

    # volume & media
    if re.fullmatch(r"(mute|unmute|মিউট|আনমিউট)( koro| করো| it| please)?", w):
        return {"tool": "media_control", "args": {"action": "mute"}}
    if re.search(r"(volume|ভলিউম|sound|সাউন্ড|awaj|আওয়াজ|শব্দ)", w) and _short(w, 7):
        steps = "3" if re.search(r"(ektu|একটু|little|bit)", w) else "10" if re.search(r"(onek|অনেক|lot|beshi|বেশি)", w) else "5"
        if re.search(r"(unmute|আনমিউট|mute|মিউট|বন্ধ|bondho|off)", w):
            return {"tool": "media_control", "args": {"action": "mute"}}
        if re.search(r"(barao|bariye|বাড়াও|বাড়িয়ে|বাড়াও|up|increase|raise|louder|jore|জোরে)", w):
            return {"tool": "media_control", "args": {"action": "volume_up", "steps": steps}}
        if re.search(r"(komao|kom koro|komiye|কমাও|কমিয়ে|কম করো|down|decrease|lower|quieter|আস্তে)", w):
            return {"tool": "media_control", "args": {"action": "volume_down", "steps": steps}}
    if _short(w, 5):
        if re.search(r"(next|skip|porer gaan|porerta|পরের গান|পরেরটা|পরের ভিডিও)", w):
            return {"tool": "media_control", "args": {"action": "next"}}
        if re.search(r"(previous|ager gaan|agerta|আগের গান|আগেরটা|আগের ভিডিও)", w):
            return {"tool": "media_control", "args": {"action": "previous"}}
        if re.fullmatch(r"(pause|resume|play pause|gaan thamao|gaan bondho koro|gaan chalu koro|গান থামাও|গান বন্ধ করো|"
                        r"গান চালু করো|ভিডিও থামাও|video thamao|pause koro|পজ করো|play koro|প্লে করো)( please)?", w):
            return {"tool": "media_control", "args": {"action": "play_pause"}}

    # YouTube / music
    m = re.fullmatch(r"(?:youtube|ইউটিউব|ইউটুব)ে?(?:\s+(?:e|এ|te|তে|-এ|on))?\s+(?P<q>.+?)\s+"
                     r"(?:chalao|chalaw|bajao|lagao|play koro|play|dekhao|চালাও|বাজাও|লাগাও|প্লে করো|দেখাও|চালু করো)", w)
    m = m or re.fullmatch(r"(?:play|চালাও|বাজাও)\s+(?P<q>.+?)(?:\s+(?:on|in)\s+youtube)?", w)
    m = m or re.fullmatch(r"(?P<q>.+?\s+(?:gaan|gan|গান|song|songs|music|মিউজিক|natok|নাটক|ভিডিও|video))\s+"
                          r"(?:chalao|chalaw|bajao|lagao|shunao|শোনাও|চালাও|বাজাও|লাগাও|play koro|প্লে করো|dekhao|দেখাও)", w)
    if m and m.group("q").strip():
        q = re.sub(r"^(?:youtube|ইউটিউব|ইউটুব)ে?\s*(?:e|এ|te|তে)?\s+", "", m.group("q")).strip()
        if q and not re.fullmatch(r"(gaan|gan|গান|song|music|মিউজিক)", q):
            return {"tool": "play_youtube", "args": {"query": q}}
        return {"tool": "play_youtube", "args": {"query": "top bangla songs" if bn else "top hits music"}}

    # open app / folder / website
    m = re.fullmatch(r"(?P<t>.+?)\s+(?:kholo|khulo|khol|kholen|open koro|open kor|open|chalu koro|start koro|"
                     r"খোলো|খুলো|খোল|খোলেন|ওপেন করো|ওপেন কর|চালু করো|স্টার্ট করো)( please| প্লিজ)?", w) \
        or re.fullmatch(r"(?:open|launch|start|go to)\s+(?P<t>.+)", w)
    if m and _short(m.group("t"), 4):
        return {"tool": "open", "args": {"name": m.group("t")}}

    # quick note: only when the sentence starts with "note"/"নোট"
    m = re.match(r"^(?:note|নোট)\s*(?:koro|করো|rakho|রাখো|kore rakho|করে রাখো|lekho|লেখো|down|that)?\s*[:,\-]?\s*(?P<n>.{3,})$",
                 nfc(text).strip(), re.I)
    if m:
        return {"tool": "add_note", "args": {"text": m.group("n").strip()}}

    if (weather := weather_request(w, bn)):
        return weather

    # news ("খবর পরে দিন" is a mis-heard "read the news", not a note)
    if (news := news_request(w)):
        news["args"]["language"] = "bn" if bn else "en"
        return news
    return None
