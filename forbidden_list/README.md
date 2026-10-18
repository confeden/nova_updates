# Список запрещённых

Один файл `forbidden_list.json` с четырьмя официальными перечнями. Его раз в сутки
обновляет workflow `.github/workflows/publish-banned-lists.yml`.

| Ключ в файле | Источник |
|---|---|
| `иноагенты` | [Реестр иностранных агентов, Минюст](https://minjust.gov.ru/ru/pages/reestr-inostryannykh-agentov/) |
| `террористы` | [Единый федеральный список террористических организаций, ФСБ](http://www.fsb.ru/fsb/npd/terror.htm) |
| `экстремисты` | [Перечень экстремистских организаций, Минюст](https://minjust.gov.ru/ru/documents/7822/) |
| `нежелательные` | [Перечень нежелательных организаций, Минюст](https://minjust.gov.ru/ru/pages/perechen-inostrannyh-i-mezhdunarodnyh-organizacij-deyatelnost-kotoryh-priznana-nezhelatelnoj-na-territorii-rossijskoj-federacii/) |

Структура файла:

```json
{
  "lists": {
    "иноагенты": {
      "title": "Реестр иностранных агентов",
      "source": "https://minjust.gov.ru/...",
      "count": 1,
      "items": [{"n": 1, "name": "...", "short_name": "", "date": "2020-01-01"}]
    }
  }
}
```

- `name` — название, `short_name` — сокращённое название (пустая строка, если его нет).
- `date` — дата внесения в формате `ГГГГ-ММ-ДД`. У самых старых записей перечня
  экстремистов отдельной даты внесения нет, поэтому указана дата решения суда,
  которую даёт сам перечень.

Если источник вернул пустой или подозрительно короткий список (меньше 70 %
опубликованного), его запись в файле не меняется, а запуск помечается как упавший.
Так недогрузившаяся страница не может стереть список. Файл коммитится только
когда какой-то список изменился.

## Где выполняется

Сайты minjust.gov.ru и fsb.ru не отвечают зарубежным адресам, поэтому workflow
выполняется на self-hosted runner `debian-banned-lists` с меткой `banned-lists`.
Он стоит на домашнем сервере с Debian в России, как systemd-сервис от пользователя
`ghrunner`; для сборки нужны `python3`, `git` и `chromium` из apt.

Если runner придётся поставить заново, в GitHub: **Settings → Actions → Runners →
New self-hosted runner → Linux**. Команды со страницы выполняются под пользователем
`ghrunner`, а при `./config.sh` добавляется метка `banned-lists`. Затем
`sudo ./svc.sh install ghrunner && sudo ./svc.sh start` в каталоге runner.

Первый запуск можно сделать вручную: **Actions → Publish banned lists → Run workflow**.
Лог первого запуска покажет столбцы и первые записи каждого источника.

Репозиторий публичный, поэтому в **Settings → Actions → General → Fork pull
request workflows from outside collaborators** выбери *Require approval for all
outside collaborators*. Иначе чужой pull request может добавить свой workflow
и выполнить его на этом сервере.
