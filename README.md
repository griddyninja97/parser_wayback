Как запускать

python script.py -o output_folder --recursive --external delete

Пример
pip install -r requirements.txt

как запускать
python script.py -o output_folder --recursive --external delete

Пример
Введите Wayback-ссылки для одного сайта (разные даты, по одной на строку).
Когда закончите — просто нажмите Enter на пустой строке:

> https://web.archive.org/web/20200101000000/http://example.com/
> https://web.archive.org/web/20210101000000/http://example.com/
> 

🏁 Аргументи
Аргумент	Опис
--recursive	Рекурсивний обхід усіх посилань на сайті
-o, --output	Шлях до директорії, де буде збережено сайт
--external	Що робити з зовнішніми посиланнями: original, delete, archive
📂 Що буде створено

У вашій вихідній директорії (output_folder) будуть:

    Повна копія сайту (index.html + вкладені сторінки)

    Всі ресурси в assets/

    Файл sitemap.xml

    Папка all_images_from_cdx/ — всі знайдені зображення

    Папка all_html_from_cdx/ — всі доступні HTML-сторінки, навіть без посилань

💡 Корисні приклади

python script.py -o saved_site --recursive --external original

python script.py --output old_version --external delete

❗ Обмеження

    Всі введені посилання мають бути з Wayback Machine та з одного домену.

    Знімки мають бути в форматі:
    https://web.archive.org/web/20200101000000/http://example.com/
Введите Wayback-ссылки для одного сайта (разные даты, по одной на строку).
Когда закончите — просто нажмите Enter на пустой строке:

> https://web.archive.org/web/20200101000000/http://example.com/
> https://web.archive.org/web/20210101000000/http://example.com/
> 

🏁 Аргументи
Аргумент	Опис
--recursive	Рекурсивний обхід усіх посилань на сайті
-o, --output	Шлях до директорії, де буде збережено сайт
--external	Що робити з зовнішніми посиланнями: original, delete, archive
📂 Що буде створено

У вашій вихідній директорії (output_folder) будуть:

    Повна копія сайту (index.html + вкладені сторінки)

    Всі ресурси в assets/

    Файл sitemap.xml

    Папка all_images_from_cdx/ — всі знайдені зображення

    Папка all_html_from_cdx/ — всі доступні HTML-сторінки, навіть без посилань

Примеры запуска
python script.py -o saved_site --recursive --external original

python script.py --output old_version --external delete

Ограниченияя
    Всі введені посилання мають бути з Wayback Machine та з одного домену.

    Знімки мають бути в форматі:
    https://web.archive.org/web/20200101000000/http://example.com/
