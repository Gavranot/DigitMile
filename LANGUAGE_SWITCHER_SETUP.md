# Language Switcher - Setup Complete ✅

## What Was Configured

### 1. Base Template with Language Switcher
**File:** `DigitMilePanel/digitmileapi/templates/admin/base_site.html`

This template:
- Extends Django's admin base template
- Adds a language dropdown in the top-right header
- Automatically available on ALL pages that extend `admin/base_site.html`

### 2. Reusable Language Switcher Component
**File:** `DigitMilePanel/digitmileapi/templates/digitmileapi/includes/language_switcher.html`

Use this for standalone pages:
```django
{% include 'digitmileapi/includes/language_switcher.html' %}
```

### 3. URL Configuration
**File:** `DigitMilePanel/digitmile/urls.py`

Added:
```python
from django.views.i18n import set_language

urlpatterns = [
    path('i18n/setlang/', set_language, name='set_language'),
    # ...
]
```

## How to Use

### For Admin Panel Pages (Already Working!)

If your page extends `admin/base_site.html`, you're done! Example:

```django
{% extends "admin/base_site.html" %}
{% load i18n %}

{% block content %}
    <h1>{% trans "My Page" %}</h1>
    <!-- Language switcher appears automatically in header -->
{% endblock %}
```

### For Custom/Standalone Pages

Include the switcher manually:

```django
<!DOCTYPE html>
<html>
<head>
    <title>My Page</title>
</head>
<body>
    {% include 'digitmileapi/includes/language_switcher.html' %}

    <!-- Your content -->
</body>
</html>
```

## Testing

1. Visit any page (e.g., `/panel/`)
2. Look for the language dropdown in the top-right corner
3. Select "Македонски" from the dropdown
4. Page reloads with the selected language
5. Language preference is saved in session

## What You Still Need to Do

1. **Add translations to your .po files:**
   ```bash
   docker-compose exec backend python manage.py makemessages -l mk
   # Edit locale/mk/LC_MESSAGES/django.po
   docker-compose exec backend python manage.py compilemessages
   ```

2. **Mark all text in templates for translation:**
   ```django
   {% load i18n %}
   {% trans "Text to translate" %}
   ```

3. **Restart Django to load new translations:**
   ```bash
   docker-compose restart backend
   ```

## Files Created/Modified

✅ Created: `digitmileapi/templates/admin/base_site.html`
✅ Created: `digitmileapi/templates/digitmileapi/includes/language_switcher.html`
✅ Modified: `digitmile/urls.py`
✅ Modified: `home.html` (example with translation tags)
✅ Updated: `TRANSLATION_GUIDE.md`

## Current Languages

- **English** (en) - Default
- **Macedonian** (mk) - Македонски

To add more languages, edit `settings.py`:
```python
LANGUAGES = [
    ('en', 'English'),
    ('mk', 'Македонски'),
    ('sq', 'Shqip'),      # Albanian
    ('sr', 'Српски'),     # Serbian
]
```

Then run `makemessages` for each new language.

## Troubleshooting

**Language switcher not showing?**
- Make sure your template extends `admin/base_site.html`
- Check that `LocaleMiddleware` is in `settings.py` MIDDLEWARE
- Verify `USE_I18N = True` in settings

**Translations not working?**
- Run `compilemessages` after editing .po files
- Restart Django server
- Check browser console for errors

**Language not persisting?**
- Make sure cookies are enabled
- Check that session middleware is configured
- Verify `django.contrib.sessions` is in INSTALLED_APPS
