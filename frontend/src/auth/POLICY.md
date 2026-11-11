# Локальные проверки пароля

`password-policy.json` содержит публичный список распространённых паролей из Django 5.2.19, его SHA-256 и диапазоны Unicode `str.isdigit()` установленного Python. Это справочные данные валидации, а не введённые пользователем пароли. Список создан Royce Williams и поставляется Django; лицензия Django сохранена в `LICENSE-Django.txt`.

Источник: `.venv/Lib/site-packages/django/contrib/auth/common-passwords.txt.gz`, оригинальный список: https://gist.github.com/roycewilliams/226886fd01572964e1431ac8afc999ce.

Проверки повторяют текущие Django MinimumLength/Common/Numeric/UserAttributeSimilarity validators. В регистрации атрибутом пользователя служит нормализованный email; `quick_ratio` сравнивает мультимножества символов. Пробелы и регистр самого отправляемого пароля сохраняются. При входе эти проверки не применяются.

При обновлении Python/Django необходимо обновить данные и повторить проверку совпадения с backend. Backend остаётся окончательной проверкой и обеспечивает уникальность email.
