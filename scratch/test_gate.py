import re
from backend.app.core.database import db_manager
from backend.app.pipeline.relevance import HeuristicRelevanceFilter

p_non_photo = re.compile(r'\b(?:search(?:ing)? for (?:another|a new|a different|better|alternative) (?:app|gallery|cloud)|search(?:ed)? (?:google|online|web|the web).*?(?:help|support|customer|care)|searching for (?:ways? to pay|answers)|lost my (?:old )?phone|find out how|can\'?t take a (?:selfie|photo)|camera (?:fails|doesn\'?t))\b', re.I)
p_pos = re.compile(r'\b(?:easy to find|finds? (?:everything|all my|easily|quickly)|great (?:search|app|gallery|tools)|love (?:how|the search|this app)|best (?:app|gallery|search)|search (?:is|works) (?:great|awesome|perfect|amazing)|convenient|reliable|handy|all time photo album|find (?:the|it|this) (?:helpful|useful|good|great)|someone \*is\* reading|very beautiful)\b', re.I)

p_struggle = re.compile(
    r'\b('
    r'can\'?t find|cannot find|couldn\'?t find|unable to find|'
    r'search (?:doesn\'?t|does not|won\'?t|fails?|sucks?|broken|returns nothing|zero|not finding|is broken|is horrible|is very bad|is useless)|'
    r'search (?:feature )?is (?:very |so )?(?:bad|poor|broken|terrible|useless)|'
    r'where (?:are|is) my (?:missing )?(?:photo|picture|receipt|video|screenshot|photos|pictures|album)|'
    r'lost (?:my|all|the) (?:photo|picture|photos|pictures)|'
    r'scrolling (?:through|forever|back|for hours)|hard to find|impossible to find|no results|wrong (?:photo|results)|'
    r'stripped|don\'?t remember|forgot|not showing up|'
    r'searched .*? and got \d+|exif dates?|how (?:do|can) i (?:search|find)|'
    r'looking for (?:the |a )?(?:receipt|photo|picture|screenshot|prescription)|'
    r'remember (?:the |buying |taking |attending )|'
    r'needed (?:the |a )?(?:photo|picture|screenshot|wi-?fi)|'
    r'need to retrieve (?:my|the)? (?:photos|pictures)|'
    r'photo search bilkul|trying to find'
    r')\b', re.I
)

p_other_bugs = re.compile(r'\b(?:add photos? to (?:my )?album|creating albums?|delete (?:from|all)|backup (?:stuck|failed)|sync(?:ing)?|duplicate|widget has no album)\b', re.I)

with db_manager.session() as conn:
    rows = conn.execute('SELECT id, raw_text FROM raw_conversations').fetchall()

fric = 0
non_fric = 0
still = []

for r in rows:
    res, reason = HeuristicRelevanceFilter.evaluate(r[1])
    if res is False:
        non_fric += 1
    else:
        t = r[1]
        if p_non_photo.search(t):
            non_fric += 1
        elif p_pos.search(t):
            non_fric += 1
        elif p_struggle.search(t):
            fric += 1
        elif p_other_bugs.search(t):
            non_fric += 1
        else:
            still.append((r[0], t))

print(f"Total reviews: {len(rows)}")
print(f"Qualified Retrieval Friction: {fric}")
print(f"Non-Friction / Noise / General: {non_fric + len(still)}")
print(f"Remaining for generic reject: {len(still)}")
