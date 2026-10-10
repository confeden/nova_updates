# Список запрещённых

Официальные перечни, которые раз в сутки обновляет workflow
`.github/workflows/publish-banned-lists.yml`:

| Файл | Источник |
|---|---|
| `иноагенты` | [Реестр иностранных агентов, Минюст](https://minjust.gov.ru/ru/pages/reestr-inostryannykh-agentov/) |
| `террористы` | [Единый федеральный список террористических организаций, ФСБ](http://www.fsb.ru/fsb/npd/terror.htm) |
| `экстремисты` | [Перечень экстремистских организаций, Минюст](https://minjust.gov.ru/ru/documents/7822/) |
| `нежелательные` | [Перечень нежелательных организаций, Минюст](https://minjust.gov.ru/ru/pages/perechen-inostrannyh-i-mezhdunarodnyh-organizacij-deyatelnost-kotoryh-priznana-nezhelatelnoj-na-territorii-rossijskoj-federacii/) |

Каждый список лежит в двух видах с одинаковым содержимым:

- `.json` для программ: `{"source", "count", "items": [{"n", "name", "short_name", "date"}]}`.
  `date` имеет формат `ГГГГ-ММ-ДД`. Если сокращённого названия нет, `short_name` будет пустой строкой.
- `.md` для чтения: нумерованная таблица «Название / Сокращённое / Дата внесения».

Дата внесения берётся из источника. У самых старых записей перечня экстремистов
отдельной даты внесения нет, поэтому для них указана дата решения суда, которую
даёт сам перечень.

Если источник вернул пустой или подозрительно короткий список (меньше 70 %
опубликованного), файл не перезаписывается, а запуск помечается как упавший.
Так недогрузившаяся страница не может стереть список.

## Где выполняется

Сайты minjust.gov.ru и fsb.ru не отвечают зарубежным адресам, поэтому workflow
выполняется на self-hosted runner с меткой `banned-lists` на сервере в России.

Настройка на Debian (один раз):

```sh
sudo apt install -y git python3 python3-venv chromium
sudo useradd -m -s /bin/bash ghrunner
sudo -iu ghrunner
```

Затем в GitHub: **Settings → Actions → Runners → New self-hosted runner → Linux**.
Выполни показанные там команды под пользователем `ghrunner`, а в `./config.sh`
добавь метку:

```sh
./config.sh --url https://github.com/confeden/nova_updates --token <токен со страницы> --labels banned-lists
exit                     # обратно в пользователя с sudo
cd /home/ghrunner/actions-runner
sudo ./svc.sh install ghrunner && sudo ./svc.sh start
```

Первый запуск можно сделать вручную: **Actions → Publish banned lists → Run workflow**.

Репозиторий публичный, поэтому в **Settings → Actions → General → Fork pull
request workflows from outside collaborators** выбери *Require approval for all
outside collaborators*. Иначе чужой pull request может добавить свой workflow
и выполнить его на этом сервере.
