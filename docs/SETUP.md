# UBAgenGitv0.01 — kurulum

Bu depo, GitHub Actions encode işçisi + Render üzerinde Discord/API köprüsü + GitHub Pages yönetim panelini içerir. Bu başlangıç sürümü eski UBAgen kodunu otomatik olarak taşımaz.

## 1. GitHub Pages
- Tercih edilen kaynak: Settings → Pages → Build and deployment → Source = **GitHub Actions**.
- Actions sekmesinden **Deploy management dashboard** workflow'unu çalıştır.
- Panel: `https://ubaparator.github.io/UBAgenGitv0.01/`.
- Pages yanlışlıkla `main / root` üzerinden yayınlanıyorsa kökteki `index.html` panelin `/pages/` yoluna yönlendirir. Otomatik Actions yayını için yine de Source = GitHub Actions seç.

## 2. Render API / Discord botu
Render → New → Web Service → bu depoyu bağla. `render.yaml` Blueprint olarak kullanılabilir. Servis adı `ubagen-github-bridge` olsa da Render farklı bir URL atarsa panelde “Servis adresini değiştir” bölümüne gerçek adresi yaz.

Render → Environment değişkenleri:
- `DISCORD_BOT_TOKEN`: Discord Developer Portal'dan aldığın bot tokenı. **Yalnızca Render'da tutulur; web sayfasına veya depoya yazılmaz.**
- `DASHBOARD_API_KEY`: uzun ve rastgele, Discord tokenından farklı bir panel erişim anahtarı.
- `GITHUB_REPOSITORY`: `ubaparator/UBAgenGitv0.01`.
- `GH_TOKEN`: encode işleri kullanılacağı zaman ekle; ilk bağlantı ve `/stats` için gerekli değil. Fine-grained tokena bu depoda gerekli Actions dispatch/contents izinlerini ver.

Panelde yalnızca `DASHBOARD_API_KEY` girilir; servis adresi varsayılan olarak `https://ubagen-github-bridge.onrender.com` gelir. Render farklı URL verdiyse panelde gelişmiş servis adresi alanını değiştir. Discord bot tokenını panelde istemek güvenli değildir; bot bağlantısını sunucu tarafında Render yapar.

## 3. GitHub Actions secrets
Repository → Settings → Secrets and variables → Actions:
- Secret `RCLONE_CONFIG`: rclone'un INI biçimindeki tam yapılandırması (isteğe bağlı).
- Secret `RENDER_HEALTH_URL`: `https://SERVIS-ADIN.onrender.com/health`.
- Variable `RCLONE_REMOTE_PATH`: yalnızca geçici çıktı klasörü, ör. `drive:UBAgen-Temporary`.

## 4. Panel ve Discord komutları
Panel; servis durumunu, Discord Gateway bağlantısını, eksik yapılandırmaları ve son uygulama loglarını gösterir.
- `/stats`: kısa bot/servis durumu.
- `/log`: son hata.
- `/discord mode:<Aç/Kapat>`: yöneticinin yeni encode işi kabulünü açıp kapatır; botu kapatıp açmaz.
- `/encodeal`: Discord'a video ve isteğe bağlı ASS/SRT dosyası ekleyerek H.264/H.265 encode talebi gönderir.

## 5. Encode ve sınırlamalar
- Encode girişi doğrudan erişilebilen HTTP(S) URL'leri veya Discord ekleridir. Magnet/torrent bu başlangıç sürümünde desteklenmez.
- H.264 CRF 21, H.265 CRF 24; ses AAC 192 kb/s. Kaynak çözünürlüğü korunur.
- Rclone yoksa çıktı bir gün saklanan GitHub Actions artifact olarak yüklenir. Temizlik workflow'u, yalnızca ayarlanan geçici klasörde 2 saatten eski MP4'leri siler.
- Discord'a canlı FPS/ETA henüz aktarılmaz; FFmpeg ayrıntıları Actions loglarındadır.
- Render ücretsiz planı uyuyabilir; GitHub Actions süre ve kota sınırlarına tabidir. Kesintisiz 7/24 çalışma garantisi yoktur.

## Güvenlik
- `DISCORD_BOT_TOKEN`, `DASHBOARD_API_KEY`, `GH_TOKEN`, `RCLONE_CONFIG` hiçbir zaman HTML/JavaScript dosyalarına veya Git deposuna commit edilmemeli.
- Panel anahtarı sayfada yalnızca açık sekmenin belleğinde tutulur; sayfayı yenilersen yeniden girmen gerekir.
