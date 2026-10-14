# UBAgenGitv0.01 — kurulum

Bu depo, GitHub Actions encode işçisi + Render üzerinde Discord/API köprüsü + GitHub Pages yönetim arayüzü iskeletini içerir. Bu ilk sürüm eski UBAgen kodunu otomatik olarak taşımıyor; depo başlangıçta yalnızca README içeriyordu.

## 1. GitHub Actions izinleri
- Repository Settings → Actions → General → Workflow permissions: okuma izinleri yeterlidir; Pages workflow ayrıca kendi dosyasında gereken `pages: write` ve `id-token: write` izinlerini tanımlar.
- Settings → Pages → Build and deployment: Source = **GitHub Actions**.
- Actions sekmesinden `Deploy management dashboard` workflow'unu çalıştır.
- Sayfa adresi: `https://ubaparator.github.io/UBAgenGitv0.01/` (Pages etkinleştirildikten sonra çalışır).

## 2. Render web service
Render'da **New → Web Service → Connect repository** ile bu depoyu seç. `render.yaml` Blueprint olarak kullanılabilir. Ortam değişkenleri:
- `DISCORD_BOT_TOKEN`: Discord bot tokenı.
- `GH_TOKEN`: encode aşamasında gerekli olacak fine-grained token; ilk `/stats` testi için gerekli değil. Sonradan ekleyeceğiz. Repository permissions altında **Contents: Read and write** ver.
- `DASHBOARD_API_KEY`: uzun ve rastgele bir yönetim anahtarı; Discord tokenıyla aynı olmasın.
- `GITHUB_REPOSITORY`: `ubaparator/UBAgenGitv0.01`.

Servis adresini GitHub repo → Settings → Secrets and variables → Actions → Variables alanında `RENDER_HEALTH_URL` olarak değil, Secrets bölümünde `RENDER_HEALTH_URL` adıyla kaydet; değer `https://SERVIS-ADIN.onrender.com/health` olmalı. Bu ping workflow'u ücretsiz servislerin uyku davranışını kesin olarak ortadan kaldırmayı garanti etmez.

## 3. Yönetim paneli ve tanılama
- Panel dosyası: `pages/index.html`; canlı adresi Pages etkinleştirilip workflow başarıyla çalışınca `https://ubaparator.github.io/UBAgenGitv0.01/` olur.
- Panelde servis adresi ve `DASHBOARD_API_KEY` girilir; **Discord tokenı veya GitHub tokenı web sayfasına girilmez**. Bunları Render → Environment bölümünde ayarla. Paneldeki tanılama; Discord Gateway, eksik tokenlar, depo hedefi, iş kabulü ve son uygulama loglarını gösterir.
- `DISCORD_BOT_TOKEN` yalnızca Render Environment'a; `GH_TOKEN` ve `DASHBOARD_API_KEY` de Render Environment'a girilir. İlk `/stats` testinde `GH_TOKEN` boş bırakılabilir; encode testinden önce eklenecek. `RCLONE_CONFIG` ve `RENDER_HEALTH_URL` GitHub Actions Secrets bölümünde kalır.

## 4. Discord botu
Discord Developer Portal'da bot oluştur, tokenı Render'a ekle ve botu sunucuya davet et. Slash komutları:
- `/encodeal video:<ek dosya> codec:<H.264/H.265> subtitle:<isteğe bağlı .ass/.ssa/.srt>`
- `/stats`: kısa servis/bot durumu
- `/log`: son hata
- `/discord mode:<Aç/Kapat>`: yönetici yetkisiyle yeni iş kabulünü aç/kapatır; botu kapatıp açmaz.

## 5. Rclone (isteğe bağlı)
GitHub → Settings → Secrets and variables → Actions → Secrets altında `RCLONE_CONFIG` oluştur. Değer, rclone'un INI biçimindeki tam yapılandırma dosyası olmalı. **Secret değerini depoya veya loglara yazma.**
Actions Variables alanında `RCLONE_REMOTE_PATH` = `drive:UBAgen-Temporary` gibi, yalnızca bu botun geçici çıktıları için ayrılmış bir uzak klasör tanımla. Zamanlanmış temizlik workflow'u bu klasördeki 2 saatten eski `.mp4` dosyalarını siler; bu yüzden bu klasöre kalıcı dosya koyma. Rclone yapılandırması yoksa çıktı 1 gün saklanan GitHub artifact olarak yüklenir.

## 6. Encode notları
- Girdiler doğrudan erişilebilen HTTP(S) video/altyazı URL'leri olmalı. Discord eklerinin CDN URL'leri kısa süreli olabilir; büyük veya süresi dolan URL'ler başarısız olabilir.
- H.264 için x264 CRF 21, H.265 için x265 CRF 24 ve medium preset kullanılır. Kaynak çözünürlük korunur; çıktı video yeniden kodlanır, ses AAC 192 kb/s olur.
- GitHub-hosted runner'ların süre, disk ve aylık kullanım sınırları vardır. Bu sistem sınırsız veya 7/24 garanti edilen bir encode sunucusu değildir.
- İş ilerleme/ETA'sı ilk sürümde Discord'a canlı aktarılmaz; ayrıntılı FFmpeg çıktısı Actions loglarında yer alır.
- GitHub Pages statik olduğundan tokenı JS dosyasına gömmeyin. Panel anahtarı kullanıcı tarafından girilir ve yalnızca sayfa belleğinde tutulur.

## Güvenlik
- `GH_TOKEN`, `DISCORD_BOT_TOKEN`, `DASHBOARD_API_KEY`, `RCLONE_CONFIG` hiçbir zaman koda commit edilmemeli.
- Bu başlangıç sürümünü kullanmadan önce test girdileriyle Actions loglarını ve uzak klasör izinlerini kontrol edin.
