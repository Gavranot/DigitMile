# DigitMile Translation Guide

This guide explains how to implement and manage translations for the DigitMile platform.

## Django Templates Translation (Already Configured!)

### Configuration Complete ✓
- **Settings configured**: Languages (English, Macedonian), LocaleMiddleware added
- **Template example**: home.html updated with translation tags
- **Ready to use**: Follow the workflow below to create translations

### Translation Workflow

#### 1. Mark Strings for Translation in Templates

Use `{% load i18n %}` at the top of each template, then:

**For simple strings:**
```django
<h1>{% trans "Teacher Login" %}</h1>
<button>{% trans "Sign In" %}</button>
```

**For multi-line text:**
```django
{% blocktrans %}
This is a longer paragraph that needs to be translated.
It can span multiple lines.
{% endblocktrans %}
```

**With variables:**
```django
{% blocktrans with name=user.name %}
Hello {{ name }}, welcome back!
{% endblocktrans %}
```

#### 2. Create Translation Files

Run these commands from `DigitMilePanel/` directory:

```bash
# Create locale directory (first time only)
mkdir locale

# Generate translation files for Macedonian
docker-compose exec backend python manage.py makemessages -l mk

# Generate for additional languages
docker-compose exec backend python manage.py makemessages -l sq  # Albanian
docker-compose exec backend python manage.py makemessages -l sr  # Serbian
```

This creates: `locale/mk/LC_MESSAGES/django.po`

#### 3. Translate the Strings

Open `locale/mk/LC_MESSAGES/django.po` and add translations:

```po
#: digitmileapi/templates/digitmileapi/home.html:275
msgid "Teacher Login"
msgstr "Најава на наставник"

#: digitmileapi/templates/digitmileapi/home.html:276
msgid "Access your DigitMile dashboard"
msgstr "Пристапете до вашата контролна табла на DigitMile"

#: digitmileapi/templates/digitmileapi/home.html:289
msgid "Username"
msgstr "Корисничко име"

#: digitmileapi/templates/digitmileapi/home.html:294
msgid "Password"
msgstr "Лозинка"

#: digitmileapi/templates/digitmileapi/home.html:298
msgid "Sign In"
msgstr "Најави се"
```

#### 4. Compile Translation Files

After editing .po files:

```bash
docker-compose exec backend python manage.py compilemessages
```

This creates: `locale/mk/LC_MESSAGES/django.mo` (binary file used by Django)

#### 5. Update Translations (When You Change Text)

After modifying templates with new text:

```bash
# Update existing translation files
docker-compose exec backend python manage.py makemessages -l mk

# Translate new strings in .po file
# Then compile again
docker-compose exec backend python manage.py compilemessages
```

### Python Code Translation

For views.py and other Python files:

```python
from django.utils.translation import gettext as _

def my_view(request):
    message = _("Welcome to DigitMile")
    messages.success(request, _("Login successful"))
```

### Language Switching UI ✅ CONFIGURED!

The language switcher has been added and is available everywhere!

**Already configured:**
- ✅ URL endpoint added to `digitmile/urls.py`
- ✅ Base template created at `digitmileapi/templates/admin/base_site.html`
- ✅ Language switcher appears in the header of all admin pages
- ✅ Reusable component created at `digitmileapi/templates/digitmileapi/includes/language_switcher.html`

**How it works:**

1. **For pages extending `admin/base_site.html`** (most of your pages):
   - Language switcher is automatically visible in the top-right header
   - No additional code needed!

2. **For standalone pages (not using admin template):**
   ```django
   {% include 'digitmileapi/includes/language_switcher.html' %}
   ```

3. **Current language is saved** in the session and persists across page loads

**Testing the language switcher:**
1. Visit any page (e.g., `/panel/`)
2. Click the language dropdown in the top-right
3. Select "Македонски"
4. Page will reload with Macedonian translations (once you've added them)

---

## Game index.html Translation

The Unity game is served as a static file by nginx, so Django templates don't work here.

### Option 1: Simple JavaScript Solution (RECOMMENDED)

Create a simple translation system with JavaScript:

**1. Create translation JSON files:**

`game/translations/en.json`:
```json
{
  "game_title": "DigitMile Game",
  "game_subtitle": "An Interactive Educational Experience",
  "how_to_play": "How to Play",
  "getting_started": "Getting Started",
  "ask_teacher": "Ask your teacher for your classroom key",
  "enter_key": "Enter the classroom key when prompted",
  "select_name": "Select your name from the student list",
  "start_playing": "Start playing and learning!",
  "about_digitmile": "About DigitMile"
}
```

`game/translations/mk.json`:
```json
{
  "game_title": "DigitMile Игра",
  "game_subtitle": "Интерактивно образовно искуство",
  "how_to_play": "Како да играте",
  "getting_started": "Почетни чекори",
  "ask_teacher": "Прашајте го вашиот наставник за клучот на училницата",
  "enter_key": "Внесете го клучот на училницата кога ќе ви биде побарано",
  "select_name": "Изберете го вашето име од списокот на ученици",
  "start_playing": "Започнете да играте и да учите!",
  "about_digitmile": "За DigitMile"
}
```

**2. Add translation script to index.html:**

```html
<script>
// Translation system
const translations = {};
let currentLang = localStorage.getItem('gameLanguage') || 'en';

async function loadTranslations(lang) {
    const response = await fetch(`translations/${lang}.json`);
    translations[lang] = await response.json();
    return translations[lang];
}

function t(key) {
    return translations[currentLang]?.[key] || key;
}

async function setLanguage(lang) {
    currentLang = lang;
    localStorage.setItem('gameLanguage', lang);
    await loadTranslations(lang);
    updatePageText();
}

function updatePageText() {
    document.querySelectorAll('[data-i18n]').forEach(el => {
        const key = el.getAttribute('data-i18n');
        el.textContent = t(key);
    });
}

// Initialize on page load
document.addEventListener('DOMContentLoaded', async () => {
    await loadTranslations(currentLang);
    updatePageText();
});
</script>
```

**3. Update HTML elements with data-i18n attributes:**

```html
<div class="game-header">
    <h1 data-i18n="game_title">DigitMile Game</h1>
    <p data-i18n="game_subtitle">An Interactive Educational Experience</p>
</div>

<div class="sidebar">
    <h2 data-i18n="how_to_play">How to Play</h2>
    <h3 data-i18n="getting_started">Getting Started</h3>
    <ul>
        <li data-i18n="ask_teacher">Ask your teacher for your classroom key</li>
        <li data-i18n="enter_key">Enter the classroom key when prompted</li>
    </ul>
</div>
```

**4. Add language switcher to game page:**

```html
<!-- Add this in the game header or wherever you want the switcher -->
<div class="game-language-switcher">
    <button onclick="setLanguage('en')" class="lang-btn">English</button>
    <button onclick="setLanguage('mk')" class="lang-btn">Македонски</button>
</div>

<style>
.game-language-switcher {
    position: absolute;
    top: 20px;
    right: 20px;
    z-index: 1000;
}

.lang-btn {
    padding: 8px 16px;
    margin: 0 5px;
    border: 2px solid #417690;
    background: white;
    color: #417690;
    border-radius: 6px;
    cursor: pointer;
    font-size: 14px;
    font-weight: 600;
    transition: all 0.3s;
}

.lang-btn:hover {
    background: #417690;
    color: white;
}

.lang-btn.active {
    background: #417690;
    color: white;
}
</style>

<script>
// Update buttons to show active state
function updateLanguageButtons() {
    document.querySelectorAll('.lang-btn').forEach(btn => {
        btn.classList.remove('active');
    });
    const activeLang = localStorage.getItem('gameLanguage') || 'en';
    document.querySelector(`.lang-btn[onclick*="${activeLang}"]`)?.classList.add('active');
}

// Call after setLanguage
async function setLanguage(lang) {
    currentLang = lang;
    localStorage.setItem('gameLanguage', lang);
    await loadTranslations(lang);
    updatePageText();
    updateLanguageButtons();
}

// Initialize
document.addEventListener('DOMContentLoaded', () => {
    updateLanguageButtons();
});
</script>
```

### Option 2: Convert to Django Template (More Integrated)

Move `game/index.html` to Django templates and serve it through a view:

**1. Create view in `digitmileapi/views.py`:**

```python
def game_view(request):
    return render(request, 'digitmileapi/game.html')
```

**2. Add URL in `digitmile/urls.py`:**

```python
urlpatterns = [
    path('', api_views.game_view, name='game'),  # Serve at root
    path('panel/', include(panel_patterns)),
]
```

**3. Move and convert `game/index.html`:**
- Copy to `digitmileapi/templates/digitmileapi/game.html`
- Add `{% load i18n %}` and translation tags
- Update static file references

**Benefits:** Uses Django's translation system, automatic language detection
**Drawbacks:** Game must be served through Django instead of nginx

---

## Best Practice Recommendations

### For Your Use Case:

1. **Django Templates** (admin panel, registration forms):
   - ✅ Use Django's built-in i18n (already configured)
   - Translation files in `locale/mk/LC_MESSAGES/`

2. **Game index.html**:
   - ✅ Use JavaScript translation (Option 1) - simple, static, fast
   - Store translations in `game/translations/*.json`
   - Language preference saved in localStorage

### Translation Workflow Summary

**Django templates:**
```bash
1. Add {% trans %} tags to templates
2. python manage.py makemessages -l mk
3. Edit locale/mk/LC_MESSAGES/django.po
4. python manage.py compilemessages
5. Restart server
```

**Game index.html:**
```bash
1. Add data-i18n attributes to HTML elements
2. Create/edit translations/*.json files
3. Refresh browser
```

---

## Common Languages for North Macedonia

Add these to `settings.py` LANGUAGES:

```python
LANGUAGES = [
    ('en', 'English'),
    ('mk', 'Македонски'),  # Macedonian
    ('sq', 'Shqip'),       # Albanian
    ('sr', 'Српски'),      # Serbian
    ('tr', 'Türkçe'),      # Turkish
]
```

---

## Testing Translations

1. **Force language for testing:**
   ```
   http://localhost:8000/panel/?language=mk
   ```

2. **Check translation coverage:**
   ```bash
   docker-compose exec backend python manage.py makemessages -l mk --no-obsolete
   ```

3. **Find untranslated strings:**
   Look for empty `msgstr ""` in .po files

---

## Tools & Resources

- **POEdit**: GUI editor for .po files (https://poedit.net/)
- **Django i18n docs**: https://docs.djangoproject.com/en/5.2/topics/i18n/
- **Translation checklist**: Always translate error messages, form labels, buttons, navigation

---

## Quick Reference

| Task | Command |
|------|---------|
| Create translation files | `python manage.py makemessages -l mk` |
| Update existing translations | `python manage.py makemessages -l mk` |
| Compile translations | `python manage.py compilemessages` |
| Add new language | Add to LANGUAGES, run makemessages |
| Clear translation cache | Restart Django server |
