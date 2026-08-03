# AI World Lens

AI World Lens, tarafsız meslek promptlarından insan görselleri üretir; görünür yaş ve cinsiyet sunumunu Gemini Vision ile sınıflandırıp referans verilerle karşılaştırır. Başarısız ve mock kayıtlar grafiklere katılmaz.

## Kurulum ve çalıştırma (Windows)

Python 3.12, SQL Server ve ODBC Driver 17 gereklidir.

```bat
venv\Scripts\activate
pip install -r requirements.txt
baslat.bat
```

Gerçek `.env` kaynak kontrolüne eklenmemelidir. `OPENAI_API_KEY` ve `GEMINI_API_KEY` gereklidir. Varsayılan üretici `gpt-image-2`, kalite `low`, boyut `1024x1024`; varsayılan çalışma 10 örnektir. Pollinations, `IMAGE_PROVIDER=pollinations` ile seçilebilen isteğe bağlı eski sağlayıcıdır.

Arayüz `http://localhost:3000`, sağlık kontrolü `http://localhost:8000/api/health` adresindedir.

## Docker ile çalıştırma

Docker Desktop açıkken proje kökünde:

```powershell
docker compose up --build
```

Arayüz `http://localhost:3000`, API dokümantasyonu `http://localhost:8000/docs`
adresinde açılır. Compose, `.env` mevcutsa anahtarları çalışma anında backend'e
aktarır; `.env` image içine kopyalanmaz. SQLite veritabanı ve üretilen görseller
Docker volume'larında kalıcıdır. Container kapatılıp tekrar açıldığında deney
kayıtları korunur.

`docker compose config` yerel `.env` değerlerini çözümleyerek terminale
yazdırabilir. API anahtarı bulunan ortamlarda bu komutun çıktısını ekran
görüntüsü, issue veya CI logu olarak paylaşmayın.

Normal kapatma:

```powershell
docker compose down
```

`docker compose down -v` kalıcı volume'ları da siler; kayıtları korumak
istiyorsanız `-v` kullanmayın.

## GitHub ve CI

`.github/workflows/ci.yml`, her `main` push'unda ve pull request'te gerçek
OpenAI/Gemini çağrısı yapmadan backend/frontend testlerini çalıştırır ve Docker
image'ının oluşturulabildiğini doğrular. Dependabot; Python, Docker base image ve
GitHub Actions güncellemelerini haftalık olarak kontrol eder.

İlk GitHub yayını için uzak repo oluşturduktan sonra:

```powershell
git add .
git commit -m "Add Docker and GitHub CI integration"
git branch -M main
git remote add origin https://github.com/KULLANICI/AI_World_Lens.git
git push -u origin main
```

GitHub repository ayarlarında `main` branch protection açıp CI kontrollerini
zorunlu yapmak önerilir. API anahtarlarını repoya eklemeyin; ileride deployment
workflow'u eklenirse GitHub Environment/Secrets kullanın.

## Vision failover

- Primary analyzer: Gemini Vision
- Fallback analyzer: OpenAI GPT-4o mini
- Fallback is never silent; the user explicitly starts re-analysis.
- Generated images are preserved when Gemini quota or service capacity is unavailable.
- Fallback re-analysis evaluates every generated image with one provider and activates the new revision atomically.
- A Prepared Experiment uses verified saved results, and Verified Replay performs no new provider API requests.

OpenAI re-analysis requires the additive `result_analyses` table. It can be
created without deleting or rewriting existing data:

```bat
venv\Scripts\python.exe migrate_add_result_analyses.py
```

Take the normal database backup first. The migration is idempotent and creates
only the missing analysis-history table.

For a controlled development-only quota simulation, set
`VISION_TEST_SIMULATE_GEMINI_QUOTA=true` in the launch terminal. Its default is
`false`; it must remain disabled in normal and presentation runs.

## Sunum ve bilimsel sınır

Canlı sunumdan önce sonuçların üretilmesi önerilir. Görünür yaş ve cinsiyet etiketleri gerçek kimlik iddiası değildir. On örnek yalnızca demo seviyesindedir; bilimsel çalışma için daha büyük örneklem, sabit protokol ve doğrulanmış referans veri gerekir.

## Design decisions

- Başarılı ve başarısız örnekler ayrılır; yalnızca doğrulanmış analizler dağılımlara girer, hatalar başarı oranında görünür kalır.
- Gruplar arasındaki fark yüzde puanla gösterilir; bu ölçü iki oranın doğrudan ve belirsiz olmayan karşılaştırmasıdır.
- Örneklem sayısı her karşılaştırmada görünürdür; sonuçların demo ölçeğinde yorumlanmasını sağlar.
- Research Observation metni mevcut oranlardan deterministik üretilir; aynı veri her zaman aynı temkinli açıklamayı verir ve yeni bir model çağrısı yapmaz.
- Canlı servislerde gecikme veya kota hatası olabileceğinden sunumdan önce veri üretmek daha güvenlidir.

## Research Mode — Ortalama Dünya

`Run 10 Samples` akışı bir **Live Demo**’dur. On örnek yöntemi görünür kılar;
bilimsel bir evren tahmini veya nüfus sonucu üretmek için yeterli değildir.
`research.html` üzerindeki Research Campaigns alanı, daha büyük örneklemleri
Study → Wave → Campaign hiyerarşisi içinde planlar. Representation Atlas ise
yalnızca kalıcı campaign kayıtlarından, seçili aktif makine analiz revision’ından
ve açıkça yapılandırılmış benchmarklardan sonuç üretir.

- Ortalama Dünya, *cultivation-inspired representational audit* (yetiştirme
  yaklaşımından esinlenen temsil denetimi) olarak çerçevelenir. İnsanlarda bir
  etki veya nedensellik ölçtüğü iddia edilmez.
- Makine analizleri `machine_provisional` olarak saklanır. İnsan kodlaması
  yapılmadıkça sonuçlar “human validated” olarak sunulmaz.
- Görünür yaş ve cinsiyet sunumu etiketleri kimlik iddiası değildir. Sistem
  etnik köken, din, milliyet, sağlık, gelir veya gerçek cinsiyet kimliği çıkarmaz.
- Türkçe ve İngilizce promptlar ayrı deney kollarıdır. Prompt dili, sürümü,
  standardizer sürümü ve scene policy wave manifestinde izlenir.
- Her prompt genel nüfusla karşılaştırılamaz. Atlas ancak prompta uygun,
  toplamı doğrulanmış ve kaynak etiketi bulunan benchmark ile sapma hesaplar;
  aksi durumda açıkça `No reference` gösterir.
- Wave yaklaşımı aynı protokolün dönemsel olarak tekrarını mümkün kılar. İlk
  campaign planı oluşturulduğunda wave parametreleri kilitlenir.
- Gerçek campaign başlatmak kota tüketir ve ücret doğurabilir. Create ve Dry Run
  işlemleri provider çağrısı yapmaz; testler yalnızca geçici SQLite ve fake/mock
  servislerle çalışır.
- Gerçek `.env` kaynak kontrolüne eklenmemeli; manifest ve API yanıtları anahtar
  değerlerini içermez.

Araştırma schema’sı ayrı ve additive’dir. Gerçek SQL Server’a uygulamadan önce
`migrate_add_research_core.py` dosyasını inceleyin ve normal veritabanı yedeğini
alın. Migration mevcut tablo veya satırları silmez/değiştirmez; yalnızca yeni
araştırma tablolarını oluşturur ve 32 nötr kavramın Türkçe/İngilizce kollarını
idempotent olarak ekler.

```bat
venv\Scripts\python.exe migrate_add_research_core.py
```

Metodolojik kapsam ve sınırlılıklar için `docs/research_methodology.md` belgesine
bakın.

## Presentation Safety

For presentation-ready experiment runs, 1536x1024 with medium quality is recommended. Keep one size and quality setting consistent within the same research wave.

Tamamlanmış ve en az bir doğrulanmış sonucu bulunan deney, dashboard üzerindeki
`Save as Presentation Backup` düğmesiyle kalıcı bir sunum snapshot'ına çevrilir.
Bu işlem yeni görsel üretmez ve Vision çağrısı yapmaz. Kaynak görseller
`frontend/assets/generations/presentation_backups/<backup-id>/` altında bağımsız
olarak kopyalanır; manifest ve her görsel SHA-256 ile doğrulanır.

Backup panelinden kayıt seçilip `Make Active` ile aktif hâle getirilir. Aynı anda
yalnızca bir backup aktiftir; önceki kayıt silinmez. `Run Presentation Preflight`,
manifest hash'ini, asset checksumlarını, provider/model snapshot'ını, filmstrip,
trajectory ve final dağılım üretimini provider çağrısı yapmadan ayrı PASS/FAIL
satırlarıyla kontrol eder.

`Open Prepared Replay`, kayıtlı deneyi mevcut Cinema içinde oynatır. Ekranda
`PREPARED REPLAY — RECORDED RUN` etiketi sürekli görünür; `LIVE` gösterilmez.
Replay OpenAI/Gemini çağrısı yapmaz, queue'ya iş eklemez ve yeni Result oluşturmaz.
Canlı deney hata verirse Cinema'daki `Open Prepared Replay` yalnızca doğrulanmış
aktif backup varsa kullanılabilir; canlı hata ve kısmi sonuçlar silinmez.

Presentation Backup tablosu additive migration ile hazırlanır. Gerçek SQL Server
üzerinde çalıştırmadan önce normal yedeği alın:

```bat
venv\Scripts\python.exe migrate_add_presentation_backups.py
```

Varsayılan güvenli, çevrimdışı test paketi:

```powershell
powershell -ExecutionPolicy Bypass -File .\run_offline_tests.ps1
```

Canlı sağlayıcı testleri varsayılan olarak skip edilir. Yalnızca bilinçli opt-in:

```powershell
$env:RUN_LIVE_API_TESTS="1"
venv\Scripts\python.exe test_key.py
```

Gerçek veritabanını düşürüp yeniden oluşturan eski test için iki ayrı onay gerekir:
`RUN_REAL_DATABASE_TESTS=1` ve `ALLOW_DESTRUCTIVE_DATABASE_TESTS=1`. Bu test normal
geliştirme veya sunum hazırlığında çalıştırılmamalıdır.

Yerel sunucuya bağlanan manuel comparison/statistics smoke testleri de varsayılan
olarak kapalıdır; bilinçli kullanım için hem `RUN_LOCAL_SERVER_TESTS=1` hem de
`RUN_REAL_DATABASE_TESTS=1` gerekir.
