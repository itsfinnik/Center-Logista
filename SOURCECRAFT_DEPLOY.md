# Деплой на SourceCraft

## ✅ Готово к деплою!

Все файлы созданы:
- ✅ `.sourcecraft.yml` - основная конфигурация
- ✅ `.sourcecraft/workflows/deploy.yml` - workflow для CI/CD
- ✅ `requirements.txt` - зависимости
- ✅ `Procfile` - команда запуска

## 🚀 Шаги для деплоя:

### 1. Загрузите изменения в SourceCraft

```bash
cd /Users/felixcollins/Desktop/24.10

git add .
git commit -m "Add SourceCraft deployment configuration"
git push origin main
```

### 2. В SourceCraft (веб-интерфейс)

1. Откройте репозиторий `center-logista`
2. Перейдите в **CI/CD** → **Manual launch**
3. В поле **"Branch to search workflow description"** выберите: `main`
4. В поле **"Workflow"** выберите: `Deploy Application`
5. В поле **"Branch to launch CI on"** выберите: `main`
6. Нажмите **"Launch now"**

### 3. Дождитесь завершения деплоя

Процесс займет 2-3 минуты:
- ⏳ Установка Python 3.9
- ⏳ Установка зависимостей (scikit-learn, fastapi, etc.)
- ⏳ Обучение ML-модели (~5 секунд)
- ✅ Запуск приложения

### 4. Ваш сайт будет доступен!

SourceCraft даст URL вида:
```
https://center-logista-<hash>.sourcecraft.dev
```

## 📋 Что произойдет при деплое:

1. **Checkout** - код загружается
2. **Python Setup** - устанавливается Python 3.9
3. **Dependencies** - устанавливаются все пакеты из requirements.txt
4. **ML Model** - автоматически создается и обучается RandomForest модель
5. **Run** - запускается FastAPI приложение
6. **HTTPS/TLS** - автоматически включается (требование конкурса!)

## 🎯 После успешного деплоя:

✅ Сайт работает на HTTPS  
✅ TLS 1.2/1.3 активен (критерий конкурса выполнен!)  
✅ ML-модель обучена и работает  
✅ Все endpoints доступны  
✅ База данных SQLite создана

## 🔧 Если возникнут проблемы:

1. Проверьте логи в разделе CI/CD → Jobs
2. Убедитесь что ветка `main` существует
3. Убедитесь что все файлы загружены: `.sourcecraft.yml` и `.sourcecraft/workflows/deploy.yml`

---

**Готово к деплою! Удачи на конкурсе! 🏆**

