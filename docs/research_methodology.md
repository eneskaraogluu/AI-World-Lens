# Ortalama Dünya — Araştırma metodolojisi

## Araştırma sorusu

Tarafsız görsel istemleri aynı üretken modelde tekrarlandığında kimler, hangi
rollerde, hangi görünür yaş sunumlarında, hangi mekânlarda ve hangi gözlenebilir
çevresel koşullarda tekrar tekrar temsil edilir?

Bu çalışma **yetiştirme yaklaşımından esinlenen bir temsil denetimidir**
(*cultivation-inspired representational audit*). İzleyici maruziyetini veya
insanlarda oluşan dünya algısını ölçmez; dolayısıyla üretken modellerin
“Ortalama Dünya Sendromu” yarattığına ilişkin nedensel bir sonuç kurmaz.

## Analiz birimi

Birincil analiz birimi, versioned bir prompt kolu için üretilen tek bir görsel
ve o görselin seçili aktif analyzer revision’ıdır. Study araştırma programını,
Wave dönemsel ve kilitli protokolü, Campaign örnekleme planını, CampaignPrompt
ise dil/variant ayrımı korunmuş deney kolunu temsil eder. Eski Live Demo
deneyleri açık bir import işlemi olmadan research wave’lerine katılmaz.

## Prompt örnekleme

Başlangıç kataloğu 32 tarafsız kavramı occupations, daily life, places ve
social roles kategorilerinde tanımlar. Her kavramın Türkçe ve İngilizce karşılığı
ayrı `PromptDefinition` kaydıdır; diller aynı sonuç havuzunda birleştirilmez.
Prompt sürümü, scene policy, expected-person policy ve applicable dimensions
manifest hash’ine katılır.

Scene policy, standardizasyon metnini belirler:

- `single_person`: tam bir birincil kişi ister.
- `multi_person` / `family_group`: kavramın doğal kişi kompozisyonunu korur.
- `place_focused`: çevreyi öne çıkarır; kişiyi zorunlu kılmaz.

Standardizer cinsiyet, etnik köken veya yaş dayatmaz. Aynı wave içinde
standardizer sürümü değiştirilemez.

## Görsel örnekleme

Campaign, her prompt kolu için hedef örnek sayısını kalıcı task slotlarına
dönüştürür. `(campaign_prompt_id, sample_index)` benzersizdir. Pause yeni görev
enqueue edilmesini durdurur ve çalışan örneklerin bitmesine izin verir. Resume
yalnızca eksik slotları ele alır. Uygulama yeniden başlatılırsa kesintiye uğramış
campaign otomatik devam etmez; güvenli biçimde paused olur ve açık resume ister.

Create ve Dry Run provider çağrısı yapmaz. Gerçek Start kota tüketebilir ve
ücret doğurabilir.

## Makine kodlaması

Analysis V2 çoklu kişi ve sıfır kişili sahneleri destekler. Kişi düzeyinde
yalnızca görünür cinsiyet sunumu ve tahmini görünür yaş grubu kodlanır. Sahne
düzeyinde setting, indoor/outdoor, urbanicity, görünür çevre bakımı, teknoloji,
araç ve kıyafet formalitesi gibi gözlenebilir ipuçları tutulur. Sonuçlar
`machine_provisional` olarak etiketlenir.

Kişi sayısı `persons` uzunluğuyla aynı değilse payload geçersizdir. Geçersiz JSON
başarılı sayılmaz. Place promptunda sıfır kişi geçerli olabilir. Single-person
promptunda sıfır veya çoklu kişi kalite bayrağı üretir. V1 projection yalnızca
gerçekten tek kişili ve uyumlu yaş kategorili sonuçlarda yapılır.

## İnsan kodlaması ve güvenirlik

Human Coder Lab bu sürümde uygulanmamıştır. Bu nedenle arayüz veya raporlar
makine sonucunu insan doğrulaması olarak sunmaz; `human_annotated` ve
`human_adjudicated` sayıları sıfır kalır. İleride iki bağımsız kör kodlayıcı,
versioned codebook, ayrı adjudication ve değişken bazlı agreement/alpha/kappa
katmanı eklenmelidir. İlk insan kararları makine analizi veya adjudication ile
üzerine yazılmamalıdır.

## Benchmark eşleme

Benchmark değerleri prompt, version, dimension ve category bazında açık kaynak
etiketiyle snapshot olarak saklanır. Aynı boyuttaki payların toplamı tam %100
değilse benchmark geçersiz kabul edilir. Kaynak yoksa `No reference` gösterilir;
eksik referans sıfır kabul edilmez. Her promptun genel nüfusla karşılaştırılabilir
olduğu varsayılmaz.

## İstatistikler

- Yüzde puan farkı: `(generated share − reference share) × 100`; birimi `pp`.
- Representation ratio: `generated share / reference share`; referans sıfırsa
  oran üretilmez ve Infinity gösterilmez.
- Oran belirsizliği: Wilson güven aralığı.
- `Unclear` değerler kategori payı denominator’ından çıkarılır, ancak ayrı
  unclear sayısı ve açık denominator kuralı korunur.
- Trajectory, sonuçları completion timestamp ve sample index ile deterministik
  sıralar. Farklı provider/model/revision kombinasyonlarını sessizce karıştırmaz.
- Atlas hücresi, varsayılan minimum machine-validated `n=10` altında
  `Insufficient sample` gösterir.

Canonical count servisi requested, queued, processing, completed, generated,
machine validated, human annotated, adjudicated, unverified, failed, excluded
ve boyut-bazlı usable sayımlarını tek noktadan üretir.

## Hariç tutma kuralları

Üretilemeyen görsel `failed`; görsel üretilmiş fakat geçerli structured analiz
alınamamışsa `unverified` olur. Yalnızca aktif ve başarılı Analysis V2 revision’ı
metriklere girer. `Unclear`, başarısızlık değildir fakat ilgili kategori payına
katılmaz. Bir sonuç farklı bir atlas category’sine aitse evidence panelinde
korunur ve ilgili hücreye neden katılmadığı açıklanır.

## Hassas özellik sınırları

Sistem görselden etnik köken, din, milliyet, sağlık durumu, gelir, sosyal sınıf
veya gerçek cinsiyet kimliği çıkarmaz. `environment_condition` insanı değil,
görüntüdeki gözlenebilir çevresel ipucunu tarif eder. Görünür sunum kodları
kişinin beyanı veya gerçek kimliği değildir.

## Longitudinal tekrar

Wave; provider/model parametreleri, prompt set hash’i, standardizer, codebook ve
benchmark sürümünü snapshot olarak tutar ve ilk campaign planında kilitlenir.
Wave klonlama, drift dashboard ve dönemler arası karşılaştırma Faz 4 kapsamında
planlanmıştır; mevcut sürüm bunları tamamlanmış gibi göstermez.

## Bilinen sınırlılıklar

- Human coding, reliability, adjudication uygulanmamıştır.
- Wave clone/drift ve export/print report uygulanmamıştır.
- Machine labels model hatalarına ve prompt diline duyarlıdır.
- Minimum örneklem eşiği tek başına temsil edicilik sağlamaz.
- Benchmark uygunluğu araştırmacı kararı ve kaynak incelemesi gerektirir.
- Sonuçlar model davranışının iç nedenlerini veya kullanıcı üzerindeki etkisini
  açıklamaz.
