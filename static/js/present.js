/* Layar presenter: hasil live, moderasi word cloud, leaderboard, dan kontrol soal. */

import {
  $,
  $$,
  api,
  toast,
  animasiAngka,
  aturLebar,
  rekamPosisi,
  mainkanFlip,
  gantiTampilan,
  bangunPodiumHtml,
  mainkanKembangApi,
  escapeHtml,
  CincinTimer,
  KlienSoket,
  KELAS_OPSI,
  adaOpsiPanjang,
  gerakDikurangi,
} from "./common.js";

const akar = document.querySelector("[data-kode]");
const KODE = akar.dataset.kode;
const MODE = akar.dataset.mode;
const TAUTAN = akar.dataset.tautan;

const isi = $("#isi-panggung");
const timer = new CincinTimer($("#timer"));

let idPertanyaanTampil = null;
let tipeTampil = null;

// Peserta yang sudah gabung (dipakai bubble lobi, urutan waktu join).
const pesertaGabung = new Map();
// Daftar peserta dipaginasi 100 per halaman — di atas itu bubble mulai
// dipaksa terlalu kecil buat tetap muat tanpa scroll (lihat sesuaikanLobi).
const UKURAN_HALAMAN_PESERTA = 100;
let halamanPeserta = 0;

// Leaderboard: hasil ditahan sampai presenter memilih untuk melihatnya, dan
// baru boleh muncul lagi setelah soal berikutnya benar-benar ditutup.
let papanTerakhir = null;
let pertanyaanTerakhir = null;
let modeTampilan = "hasil"; // "hasil" | "leaderboard"
let timerLeaderboardOtomatis = null; // jeda 3 detik sebelum leaderboard tampil sendiri setelah soal ditutup

function batalkanLeaderboardOtomatis() {
  clearTimeout(timerLeaderboardOtomatis);
  timerLeaderboardOtomatis = null;
}

// Hasil sengaja ditahan dulu supaya layar tidak menampilkan grafik dari satu
// dua suara pertama — itu bikin audiens ikut-ikutan dan hasilnya bias.
const AMBANG_TAMPIL = 0.5; // porsi partisipan online yang harus menjawab (Survey Mode)
const KUIS = MODE === "quiz";
let hasilTerbuka = false;
let puncakOnline = 0;

/** Berapa jawaban yang dibutuhkan sebelum hasil muncul di layar. */
function ambangJawaban() {
  return Math.max(1, Math.ceil(puncakOnline * AMBANG_TAMPIL));
}

/** Jumlah online dipakai sebagai puncak supaya angka acuan tidak turun
    hanya karena ada partisipan yang sinyalnya sempat putus. */
function catatOnline(jumlah) {
  if (typeof jumlah !== "number") return;
  $("#jumlah-online").textContent = jumlah;
  if (jumlah > puncakOnline) puncakOnline = jumlah;
}

/* ------------------------------------------------------- Muat layar ----- */

/**
 * Di mode Layar Penuh, konten tidak boleh sampai bikin scroll — soal atau
 * opsi yang kepanjangan lebih baik mengecil proporsional (seperti zoom-out)
 * daripada terpotong scrollbar di depan audiens. Di luar Layar Penuh, scroll
 * biasa tetap dibiarkan (wajar untuk browsing normal).
 */
function sesuaikanUkuranPanggung() {
  const konten = isi.firstElementChild;
  if (!konten) return;

  // Reset dulu supaya pengukuran berikutnya tidak kena bekas skala lama.
  konten.style.transform = "";
  konten.style.width = "";
  isi.style.maxHeight = "";
  isi.style.overflow = "";
  isi.style.overflowX = "";
  isi.style.overflowY = "";

  if (!document.fullscreenElement) return;

  // atasIsi cuma bergantung pada apa yang ada DI ATAS #isi-panggung (topbar +
  // kepala kartu), bukan pada tinggi isinya sendiri — jadi aman diukur
  // langsung. Ruang untuk #kontrol di bawah dihitung dari tinggi aslinya
  // (offsetHeight, juga tidak bergantung tinggi #isi-panggung) supaya tidak
  // ada lingkaran ukur-mengukur.
  const kontrol = $("#kontrol");
  const paddingBawahWadah = parseFloat(getComputedStyle(akar).paddingBottom || "0");
  const atasIsi = isi.getBoundingClientRect().top;
  let cadanganBawah = paddingBawahWadah + 8;
  if (kontrol) {
    const gaya = getComputedStyle(kontrol);
    cadanganBawah += kontrol.offsetHeight + parseFloat(gaya.marginTop || "0");
  }
  const tersedia = Math.max(160, window.innerHeight - atasIsi - cadanganBawah);

  isi.style.maxHeight = `${tersedia}px`;
  isi.style.overflowX = "hidden";

  // BUG NYATA yang sempat kejadian: `konten` (elemen yang di-scale) duduk
  // di DALAM padding atas+bawah #isi-panggung (kartu-isi), jadi ruang yang
  // sungguh-sungguh tersedia untuknya lebih kecil dari `tersedia` (yang
  // masih termasuk padding). Tanpa dikurangi, skala yang dihitung selalu
  // sedikit kurang kecil — baris terakhir podium/leaderboard kepotong tepat
  // sebesar padding itu (~24-48px), meski keliatan "sudah di-scale".
  const gayaIsi = getComputedStyle(isi);
  const paddingIsi =
    parseFloat(gayaIsi.paddingTop || "0") + parseFloat(gayaIsi.paddingBottom || "0");
  const tersediaKonten = Math.max(80, tersedia - paddingIsi);

  const dibutuhkan = konten.scrollHeight;
  let skala = 1;
  if (dibutuhkan > tersediaKonten) {
    // Sengaja TIDAK ada batas bawah untuk skala ini — konten kecil di layar
    // sempit lebih baik daripada baris terakhir hilang sama sekali tanpa
    // cara untuk melihatnya.
    skala = tersediaKonten / dibutuhkan;
    konten.style.transformOrigin = "top left";
    konten.style.transform = `scale(${skala})`;
    konten.style.width = `${100 / skala}%`;
  }
  // Jaring pengaman terakhir kalau toleransi pembulatan masih menyisakan
  // sedikit kelebihan: kartu ini sendiri yang scroll (masih dalam batas
  // kartu, tidak terasa seperti scroll halaman) daripada sebagian konten
  // tak pernah terlihat sama sekali.
  isi.style.overflowY = dibutuhkan * skala > tersediaKonten ? "auto" : "hidden";
}

/**
 * Ukuran baris leaderboard (panel utama, bukan sidebar) proporsional
 * terhadap ruang yang tersedia DIBAGI jumlah peserta — 5 orang tampil besar
 * memenuhi layar, 50 orang otomatis lebih ringkas — bukan ukuran tetap yang
 * kelihatan kecil sendirian di layar proyektor besar atau kepotong kalau
 * pesertanya banyak.
 */
function skalakanPapanUtama() {
  const wadah = $("#papan-utama-isi");
  if (!wadah) return;

  if (!document.fullscreenElement) {
    wadah.style.removeProperty("--tinggi-baris");
    return;
  }

  const jumlahBaris = $$(".papan-baris", wadah).length;
  if (!jumlahBaris) return;

  const kontrol = $("#kontrol");
  const paddingBawahWadah = parseFloat(getComputedStyle(akar).paddingBottom || "0");
  const atas = wadah.getBoundingClientRect().top;
  let cadanganBawah = paddingBawahWadah + 8;
  if (kontrol) {
    const gaya = getComputedStyle(kontrol);
    cadanganBawah += kontrol.offsetHeight + parseFloat(gaya.marginTop || "0");
  }
  const tersedia = Math.max(160, window.innerHeight - atas - cadanganBawah);
  // Sengaja TIDAK ada batas bawah — 10 baris harus selalu muat tanpa scroll,
  // walau di viewport pendek baris jadi kecil. Batas atas 150px saja, supaya
  // sedikit peserta tidak jadi raksasa tak wajar. CSS (.papan-baris.besar)
  // punya floor sendiri yang jauh lebih kecil dari sini, jadi kombinasi
  // keduanya tetap menyisakan sedikit ruang untuk sesuaikanUkuranPanggung()
  // membulatkan kalau masih ada selisih kecil.
  const tinggiBaris = Math.min(150, tersedia / jumlahBaris);
  wadah.style.setProperty("--tinggi-baris", `${tinggiBaris}px`);
}

/**
 * Layar lobi kuis: kotak "Peserta Bergabung" (kanan) dibatasi setinggi
 * ruang yang tersisa di layar (supaya tombol kontrol di bawahnya tidak
 * perlu di-scroll), dan bubble nama di dalamnya dicari ukuran SEBESAR
 * MUNGKIN yang masih muat lewat binary search pada --bubble-skala — bukan
 * transform: scale pada wadahnya. Alasan: wadah bubble itu flex-wrap,
 * jadi transform+lebar-kompensasi (dipakai di tempat lain seperti podium)
 * bikin browser menghitung ulang wrapping-nya di lebar yang DIBESARKAN
 * dulu sebelum diperkecil — hasilnya baris jauh lebih sedikit dari yang
 * seharusnya, dan bubble akhir kelihatan kecil padahal kotaknya sendiri
 * masih menyisakan banyak ruang kosong. Kotak QR (kiri) sengaja TIDAK
 * disamakan tingginya — biar setinggi isinya saja.
 */
function sesuaikanLobi() {
  const panggung = $("#panggung");
  const kartuPeserta = $("#kartu-peserta-lobi");
  const wadahPeserta = $("#daftar-peserta-lobi");
  if (
    !panggung ||
    !panggung.classList.contains("tampilan-lobi") ||
    !kartuPeserta ||
    !wadahPeserta ||
    kartuPeserta.classList.contains("sembunyi")
  ) {
    return;
  }
  const isiKartu = wadahPeserta.closest(".kartu-isi");
  if (!isiKartu) return;

  // Reset dulu supaya pengukuran di bawah selalu mulai dari ukuran normal
  // (skala 1), bukan menumpuk dari hasil perhitungan sebelumnya.
  isiKartu.style.maxHeight = "";
  isiKartu.style.overflowY = "";
  wadahPeserta.style.removeProperty("--bubble-skala");

  const kontrol = $("#kontrol");
  const atasKartu = kartuPeserta.getBoundingClientRect().top;
  let cadanganBawah = 24;
  if (kontrol) {
    const gaya = getComputedStyle(kontrol);
    cadanganBawah += kontrol.offsetHeight + parseFloat(gaya.marginTop || "0");
  }
  const kepala = kartuPeserta.querySelector(".kartu-kepala");
  const tinggiKepala = kepala ? kepala.offsetHeight : 0;
  // Navigasi ‹ dots › (kalau ada, karena daftar dipaginasi) ikut makan
  // jatah ruang di dalam kartu-isi — dikurangi dulu dari budget bubble.
  // marginTop dihitung terpisah karena offsetHeight TIDAK termasuk margin.
  const nav = $("#paginasi-peserta");
  let tinggiNav = 0;
  if (nav) {
    const gayaNav = getComputedStyle(nav);
    tinggiNav = nav.offsetHeight + parseFloat(gayaNav.marginTop || "0");
  }
  // BUG NYATA yang sempat kejadian (sama persis dengan kasus podium
  // sebelumnya): #kartu-isi punya padding vertikal sendiri (.kartu-isi
  // { padding: 24px 26px }) yang HARUS dikurangi dari budget kontennya —
  // max-height yang di-set di elemen ini adalah tinggi border-box
  // (termasuk padding), tapi children di dalamnya (bubble + nav) cuma
  // punya ruang SISA setelah padding itu. Tanpa dikurangi, target
  // ruangBubble selalu ~48px lebih longgar dari yang sungguhan tersedia,
  // jadi kartu-isi jadi overflow persis sebesar padding itu.
  const gayaIsi = getComputedStyle(isiKartu);
  const paddingIsi = parseFloat(gayaIsi.paddingTop || "0") + parseFloat(gayaIsi.paddingBottom || "0");
  const batasLayar = Math.max(200, window.innerHeight - atasKartu - cadanganBawah);
  const ruangIsi = Math.max(120, batasLayar - tinggiKepala);
  const ruangBubble = Math.max(60, ruangIsi - paddingIsi - tinggiNav);

  // Sudah muat di ukuran normal — biarkan kotak setinggi isinya saja,
  // jangan dipaksa jadi kotak tinggi kosong.
  if (wadahPeserta.scrollHeight <= ruangBubble) {
    isiKartu.style.maxHeight = `${ruangIsi}px`;
    return;
  }

  // Cari skala terbesar (mendekati 1) yang bikin grid bubble beneran muat.
  let bawah = 0.28; // lantai keterbacaan, kira-kira ~10px dari basis 13px
  let atas = 1;
  for (let i = 0; i < 8; i++) {
    const tengah = (bawah + atas) / 2;
    wadahPeserta.style.setProperty("--bubble-skala", tengah.toFixed(3));
    if (wadahPeserta.scrollHeight <= ruangBubble) bawah = tengah;
    else atas = tengah;
  }
  wadahPeserta.style.setProperty("--bubble-skala", bawah.toFixed(3));
  isiKartu.style.maxHeight = `${ruangIsi}px`;
  // Jaring pengaman kalau peserta ekstrem banyak dan lantai skala masih
  // menyisakan sedikit kelebihan: kotak ini sendiri yang scroll (bukan
  // seluruh halaman) daripada sebagian bubble tak pernah terlihat.
  isiKartu.style.overflowY = wadahPeserta.scrollHeight > ruangBubble ? "auto" : "hidden";
}

// skalakanPapanUtama harus jalan LEBIH DULU: dia menentukan ukuran baris
// leaderboard, baru sesuaikanUkuranPanggung mengukur apakah hasilnya masih
// kepanjangan dan perlu di-scale-down lagi.
document.addEventListener("fullscreenchange", skalakanPapanUtama);
window.addEventListener("resize", skalakanPapanUtama);
document.addEventListener("fullscreenchange", sesuaikanUkuranPanggung);
window.addEventListener("resize", sesuaikanUkuranPanggung);
document.addEventListener("fullscreenchange", sesuaikanLobi);
window.addEventListener("resize", sesuaikanLobi);
// Google Font (Plus Jakarta Sans, display=swap) sering baru selesai dimuat
// SETELAH render pertama — teks jadi berganti metrik (lebar/tinggi) dan bisa
// tumbuh lebih tinggi dari yang terukur saat sesuaikanUkuranPanggung() pertama
// kali jalan. Tanpa ini, kelebihan tinggi itu diam-diam terpotong
// (overflowY sudah kadung dikunci "hidden" dari pengukuran lama) — bukan
// discale ulang seperti yang seharusnya.
if (document.fonts && document.fonts.ready) {
  document.fonts.ready.then(() => sesuaikanUkuranPanggung());
}

/* -------------------------------------------------------- Hitung mundur - */

let intervalHitungMundur = null;

/** Soal baru saja diaktifkan: tampilkan pertanyaannya dulu + hitung mundur,
    opsi jawaban baru muncul setelah server benar-benar membuka soal. */
function gambarHitungMundur(pertanyaan, detik) {
  clearInterval(intervalHitungMundur);
  batalkanLeaderboardOtomatis();
  idPertanyaanTampil = null;
  tipeTampil = null;
  timer.sembunyikan();
  $("#btn-tutup").disabled = true;
  $("#btn-berikutnya").disabled = true;
  const tombolPapan = $("#btn-papan");
  if (tombolPapan) tombolPapan.disabled = true;
  const kartuPeserta = $("#kartu-peserta-lobi");
  if (kartuPeserta && !kartuPeserta.classList.contains("sembunyi")) {
    kartuPeserta.classList.add("sembunyi");
    rapikanKolom();
  }

  gantiTampilan(isi, () => {
    const el = document.createElement("div");
    el.innerHTML = `
      <div class="chip mb-16">Pertanyaan ${pertanyaan.urutan_ke} dari ${pertanyaan.total_soal}</div>
      <div class="pertanyaan-baris mb-24">
        ${pertanyaan.gambar ? `<img class="pertanyaan-gambar" src="${pertanyaan.gambar}" alt="">` : ""}
        <div class="tumbuh pertanyaan-besar">${escapeHtml(pertanyaan.teks)}</div>
      </div>
      <div class="tengah">
        <div class="hitung-mundur-angka" id="angka-mundur">${detik}</div>
        <p class="muted mt-8">Bersiap-siap…</p>
      </div>`;
    return el;
  }).then(() => sesuaikanUkuranPanggung());

  mulaiAnimasiHitungMundur(detik);
}

function mulaiAnimasiHitungMundur(detik) {
  let sisa = detik;
  const tampilkan = (n) => {
    const el = $("#angka-mundur");
    if (!el) return;
    el.textContent = String(n);
    if (!gerakDikurangi()) {
      el.animate(
        [{ transform: "scale(1.4)", opacity: 0 }, { transform: "scale(1)", opacity: 1 }],
        { duration: 380, easing: "cubic-bezier(0.34,1.56,0.64,1)" }
      );
    }
  };
  tampilkan(sisa);
  intervalHitungMundur = setInterval(() => {
    sisa -= 1;
    if (sisa <= 0) {
      clearInterval(intervalHitungMundur);
      return;
    }
    tampilkan(sisa);
  }, 1000);
}

/* ------------------------------------------------------------- Lobi ----- */

function gambarLobi() {
  batalkanLeaderboardOtomatis();
  idPertanyaanTampil = null;
  tipeTampil = null;
  timer.sembunyikan();
  gantiTampilan(isi, () => {
    const el = document.createElement("div");
    el.innerHTML = `
      <div class="qr-kotak">
        <img src="/qr/${KODE}.svg" alt="QR code untuk bergabung ke sesi ${KODE}" width="168" height="168" id="qr-img" style="cursor:zoom-in">
        <div class="tumbuh">
          <div class="muted mb-8">Buka di HP lalu masukkan kode</div>
          <div class="kode-raksasa">${KODE}</div>
          <div class="muted mt-8" style="overflow-wrap:anywhere">${escapeHtml(TAUTAN)}</div>
        </div>
      </div>
      <p class="muted mt-24">Belum ada pertanyaan yang dibuka. Klik “Mulai” untuk memulai.</p>`;
    return el;
  }).then(() => {
    const qr = $("#qr-img");
    if (qr) qr.addEventListener("click", bukaZoomQr);
    sesuaikanUkuranPanggung();
  });

  if (KUIS) {
    const kartuPeserta = $("#kartu-peserta-lobi");
    // gambarLobi() dipanggil ulang tiap kali presenter resync (WS "sinkron"
    // — misalnya balik dari tab lain, lihat _sambungUlangSegera di
    // common.js) walau sudah di layar lobi. Reset ke halaman 1 HANYA kalau
    // ini genuinely baru masuk ke lobi (sebelumnya "sembunyi") — supaya
    // presenter yang lagi lihat halaman 2/3 daftar peserta tidak keplanting
    // balik ke halaman 1 tiap kali dia sempat pindah tab sebentar.
    const masukBaru = kartuPeserta.classList.contains("sembunyi");
    kartuPeserta.classList.remove("sembunyi");
    if (masukBaru) halamanPeserta = 0;
    gambarHalamanPeserta();
    perbaruiJumlahPeserta();
  }
  rapikanKolom();
}

/** Perbesar QR code dalam overlay — berguna dipindai dari jarak jauh di ruangan besar. */
function bukaZoomQr() {
  if ($(".qr-lightbox")) return;
  const overlay = document.createElement("div");
  overlay.className = "qr-lightbox";
  overlay.innerHTML = `<img src="/qr/${KODE}.svg" alt="QR code diperbesar">`;
  overlay.addEventListener("click", () => overlay.remove());
  document.addEventListener("keydown", function tutupEsc(e) {
    if (e.key === "Escape") {
      overlay.remove();
      document.removeEventListener("keydown", tutupEsc);
    }
  });
  document.body.appendChild(overlay);
}

/** Hash kecil deterministik — id partisipan yang berurutan (1,2,3,4,...)
    jangan sampai menghasilkan pola warna/ukuran yang ikut berurutan juga
    (itu yang bikin bubble kelihatan seperti grid rapi, bukan acak). */
function hashKecil(n, garam) {
  let h = (n * 2654435761 + garam * 40503) >>> 0;
  h = (h ^ (h >>> 13)) >>> 0;
  return h;
}

/** Tambah satu bubble nama ke wadah lobi, kalau belum ada. */
function tambahBubblePeserta(wadah, pid, nickname) {
  if (wadah.querySelector(`[data-pid="${pid}"]`)) return;
  const el = document.createElement("span");
  // Cuma warna yang digilir (4 warna kategori) supaya lobi tetap hidup —
  // ukurannya seragam kecil supaya daftar rapi seperti daftar nama biasa,
  // bukan tag cloud acak. Tetap konsisten untuk id yang sama tiap render ulang.
  const warna = (hashKecil(pid, 1) % 4) + 1;
  el.className = `chip peserta-chip warna-${warna}`;
  el.dataset.pid = String(pid);
  el.textContent = nickname;
  wadah.appendChild(el);
  if (!gerakDikurangi()) {
    el.animate(
      [{ opacity: 0, transform: "scale(0.7)" }, { opacity: 1, transform: "scale(1)" }],
      { duration: 320, easing: "cubic-bezier(0.34,1.56,0.64,1)", fill: "backwards" }
    );
  }
}

function perbaruiJumlahPeserta() {
  const chip = $("#jumlah-peserta-lobi");
  if (chip) animasiAngka(chip, pesertaGabung.size, { durasi: 260 });
}

function totalHalamanPeserta() {
  return Math.max(1, Math.ceil(pesertaGabung.size / UKURAN_HALAMAN_PESERTA));
}

/** Render ulang bubble untuk halamanPeserta saat ini (0-based), plus navigasi halamannya. */
function gambarHalamanPeserta(transisi = false) {
  const wadah = $("#daftar-peserta-lobi");
  if (!wadah) return;
  const total = totalHalamanPeserta();
  halamanPeserta = Math.min(Math.max(halamanPeserta, 0), total - 1);

  const semua = Array.from(pesertaGabung, ([pid, nickname]) => ({ pid, nickname }));
  const mulai = halamanPeserta * UKURAN_HALAMAN_PESERTA;
  const potongan = semua.slice(mulai, mulai + UKURAN_HALAMAN_PESERTA);

  const render = () => {
    wadah.replaceChildren();
    potongan.forEach(({ pid, nickname }) => tambahBubblePeserta(wadah, pid, nickname));
    gambarPaginasiPeserta(total);
    sesuaikanLobi();
  };

  // Transisi halus cuma dipakai saat pindah halaman lewat klik (bukan saat
  // render pertama kali) — supaya pergantian isi terasa mulus, bukan
  // "loncat" mengganti semua bubble sekaligus.
  if (transisi && !gerakDikurangi()) {
    wadah.animate([{ opacity: 1 }, { opacity: 0 }], { duration: 120, easing: "ease-in", fill: "forwards" }).onfinish =
      () => {
        render();
        // fill "forwards" WAJIB di sini juga — animasi fade-out sebelumnya
        // masih menahan opacity:0 (efeknya belum dibatalkan), jadi tanpa
        // fill di fade-in ini, begitu animasinya selesai opacity balik
        // "menang" ke hasil animasi SEBELUMNYA (0) dan bubble-nya jadi tak
        // pernah kelihatan lagi walau datanya sudah benar ter-render.
        wadah.animate([{ opacity: 0 }, { opacity: 1 }], { duration: 220, easing: "ease-out", fill: "forwards" });
      };
  } else {
    render();
  }
}

/** Navigasi ‹ dots › di bawah daftar peserta — cuma tampil kalau lebih dari satu halaman. */
function gambarPaginasiPeserta(total) {
  const isiKartu = $("#kartu-peserta-lobi .kartu-isi");
  let nav = $("#paginasi-peserta");
  if (total <= 1) {
    if (nav) nav.remove();
    return;
  }
  if (!nav) {
    nav = document.createElement("div");
    nav.className = "paginasi-peserta";
    nav.id = "paginasi-peserta";
    isiKartu.appendChild(nav);
  }
  const ganti = (h) => {
    halamanPeserta = h;
    gambarHalamanPeserta(true);
  };
  nav.innerHTML = `
    <button class="btn-panah" id="btn-peserta-sebelum" ${halamanPeserta === 0 ? "disabled" : ""} aria-label="Halaman sebelumnya">‹</button>
    <div class="paginasi-dots">
      ${Array.from({ length: total }, (_, i) => `<button class="dot${i === halamanPeserta ? " aktif" : ""}" data-halaman="${i}" aria-label="Halaman ${i + 1}"></button>`).join("")}
    </div>
    <button class="btn-panah" id="btn-peserta-berikut" ${halamanPeserta === total - 1 ? "disabled" : ""} aria-label="Halaman berikutnya">›</button>`;
  const sebelum = $("#btn-peserta-sebelum", nav);
  if (sebelum) sebelum.addEventListener("click", () => ganti(Math.max(0, halamanPeserta - 1)));
  const berikut = $("#btn-peserta-berikut", nav);
  if (berikut) berikut.addEventListener("click", () => ganti(Math.min(total - 1, halamanPeserta + 1)));
  $$(".dot", nav).forEach((d) => d.addEventListener("click", () => ganti(Number(d.dataset.halaman))));
}

/** Peserta baru gabung: simpan, dan tampilkan bubble kalau presenter sedang di layar lobi. */
function tambahPesertaLobi(pid, nickname) {
  if (pesertaGabung.has(pid)) return;
  pesertaGabung.set(pid, nickname);
  perbaruiJumlahPeserta();

  // Cuma perlu render bubble barunya kalau dia jatuh di halaman yang
  // sedang dilihat presenter — kalau di halaman lain, cukup titik
  // navigasinya saja yang diperbarui (jumlah halaman mungkin bertambah).
  const indeks = pesertaGabung.size - 1;
  const halamanTujuan = Math.floor(indeks / UKURAN_HALAMAN_PESERTA);
  const total = totalHalamanPeserta();
  gambarPaginasiPeserta(total);
  if (halamanTujuan === halamanPeserta) {
    const wadah = $("#daftar-peserta-lobi");
    if (wadah) tambahBubblePeserta(wadah, pid, nickname);
    sesuaikanLobi();
  }
}

/** Layar penutup: sesi sudah berakhir — podium untuk quiz, ucapan terima kasih untuk survey. */
function gambarSesiSelesai(sesi, leaderboard) {
  batalkanLeaderboardOtomatis();
  idPertanyaanTampil = null;
  tipeTampil = null;
  timer.sembunyikan();
  $("#btn-tutup").disabled = true;
  $("#btn-berikutnya").disabled = true;
  const tombolPapan = $("#btn-papan");
  if (tombolPapan) tombolPapan.disabled = true;
  const kartuPeserta = $("#kartu-peserta-lobi");
  if (kartuPeserta) kartuPeserta.classList.add("sembunyi");
  rapikanKolom();

  const adaPodium = KUIS && leaderboard && leaderboard.podium && leaderboard.podium.length;
  gantiTampilan(isi, () => {
    const el = document.createElement("div");
    if (adaPodium) {
      el.innerHTML = `
        <div class="tengah mb-24">
          <h2 style="font-size:24px">🎉 Kuis Telah Berakhir!</h2>
          <p class="tebal mt-8" style="color:var(--accent-deep)">Selamat kepada para pemenang!</p>
          <p class="muted mt-8">${escapeHtml((sesi && sesi.judul) || "")}</p>
        </div>
        <div id="podium-wadah"></div>`;
    } else {
      el.className = "tengah";
      el.innerHTML = `
        <div class="lencana-hasil">✓</div>
        <h2 style="font-size:22px">Sesi telah berakhir</h2>
        <p class="muted mt-8">${escapeHtml((sesi && sesi.judul) || "")}</p>
        <p class="muted mt-16">Terima kasih untuk survey!</p>`;
    }
    return el;
  }).then(() => {
    if (adaPodium) {
      $("#podium-wadah").innerHTML = bangunPodiumHtml(leaderboard, null, true);
      sesuaikanUkuranPanggung();
      mainkanRevealPodium();
    } else {
      sesuaikanUkuranPanggung();
    }
  });
}

/**
 * Ungkap podium bertahap alih-alih langsung muncul semua sekaligus: tabel
 * peringkat 10 → 4 fade-in satu-satu (cepat), lalu podium 🥉 → 🥈, jeda
 * "Dan juaranya adalah…", baru 🥇 muncul berbarengan dengan confetti —
 * jadi juara #1 memang yang terakhir diumumkan, bukan langsung kelihatan
 * sejak awal layar ini terbuka.
 */
function mainkanRevealPodium() {
  const wadah = $("#podium-wadah");
  if (!wadah) return;
  const baris = $$(".papan-lanjutan .papan-baris", wadah); // urutan peringkat 4→10 (menaik)
  const kolom3 = wadah.querySelector(".podium-3");
  const kolom2 = wadah.querySelector(".podium-2");
  const kolom1 = wadah.querySelector(".podium-1");

  if (gerakDikurangi()) {
    mainkanKembangApi();
    return;
  }

  const masuk = (el, { durasi = 220, geser = 8, easing = "ease-out" } = {}) => {
    if (!el) return;
    // .papan-baris (baris tabel) punya CSS "transition: opacity ..." sendiri
    // (dipakai FLIP leaderboard di tempat lain) — kalau dibiarkan, transisi
    // itu ikut bereaksi setiap opacity-nya diubah lewat inline style dan
    // BEREBUTAN sama animate() di bawah, hasilnya baris ini balik tak
    // kelihatan lagi (kalah dari transisi CSS-nya sendiri). Matikan dulu
    // transition-nya supaya cuma animate() ini yang mengontrol opacity.
    el.style.transition = "none";
    el.style.opacity = "0";
    el.animate(
      [{ opacity: 0, transform: `translateY(${geser}px) scale(0.94)` }, { opacity: 1, transform: "none" }],
      { duration: durasi, easing, fill: "forwards" }
    );
  };

  // Tabel diungkap dari peringkat TERBAWAH ke atas (10 → 4), cepat —
  // ini cuma pemanasan sebelum podium, jadi tidak perlu jeda lama.
  const JEDA_BARIS = 90;
  [...baris].reverse().forEach((el, i) => {
    el.style.transition = "none";
    el.style.opacity = "0";
    setTimeout(() => masuk(el, { durasi: 200, geser: 6 }), i * JEDA_BARIS);
  });
  let t = baris.length * JEDA_BARIS + 150;

  setTimeout(() => masuk(kolom3, { durasi: 420, easing: "cubic-bezier(0.34,1.56,0.64,1)" }), t);
  t += 850;
  setTimeout(() => masuk(kolom2, { durasi: 420, easing: "cubic-bezier(0.34,1.56,0.64,1)" }), t);
  t += 900;

  const waktuSuspense = t;
  setTimeout(() => {
    const teks = document.createElement("div");
    teks.className = "podium-suspense";
    teks.id = "podium-suspense";
    teks.textContent = "🥁 Dan juaranya adalah…";
    wadah.before(teks);
  }, waktuSuspense);
  t += 1300;

  setTimeout(() => {
    const teks = $("#podium-suspense");
    if (teks) teks.remove();
    masuk(kolom1, { durasi: 520, geser: 14, easing: "cubic-bezier(0.34,1.56,0.64,1)" });
    mainkanKembangApi();
  }, t);
}

/* ------------------------------------------------- Kerangka pertanyaan -- */

function gambarKerangka(pertanyaan) {
  idPertanyaanTampil = pertanyaan.id;
  tipeTampil = pertanyaan.tipe;
  hasilTerbuka = false;
  return gantiTampilan(isi, () => {
    const el = document.createElement("div");
    el.innerHTML = `
      <div class="chip mb-16" id="chip-nomor">Pertanyaan ${pertanyaan.urutan_ke} dari ${pertanyaan.total_soal}</div>
      <div class="pertanyaan-baris mb-8">
        ${pertanyaan.gambar ? `<img class="pertanyaan-gambar" src="${pertanyaan.gambar}" alt="">` : ""}
        <div class="tumbuh pertanyaan-besar">${escapeHtml(pertanyaan.teks)}</div>
      </div>
      <div class="muted mb-24" id="ringkas-jawaban">0 partisipan telah menjawab</div>
      <div id="wadah-hasil"></div>`;
    return el;
  });
}

/* ------------------------------------------------------- Hasil: MC ------ */

function gambarHasilMC(hasil) {
  const wadah = $("#wadah-hasil");
  if (!wadah) return;
  const maks = Math.max(...hasil.opsi.map((o) => o.jumlah), 0);

  hasil.opsi.forEach((o, i) => {
    let baris = wadah.querySelector(`[data-opsi="${o.id}"]`);
    if (!baris) {
      baris = document.createElement("div");
      baris.className = "bar-baris";
      baris.dataset.opsi = String(o.id);
      // Warna kategori per opsi supaya tiap bar gampang dibedakan sekilas.
      baris.innerHTML = `
        <div class="bar-label"></div>
        <div class="bar-jalur"><div class="bar-isi warna-${(i % 4) + 1}"></div></div>
        <div class="bar-angka"></div>`;
      baris.querySelector(".bar-label").textContent = o.teks;
      wadah.appendChild(baris);
    }
    const isiBar = baris.querySelector(".bar-isi");
    const teratas = o.jumlah > 0 && o.jumlah === maks;
    baris.classList.toggle("teratas", teratas);
    isiBar.classList.toggle("teratas", teratas && !hasil.ditutup);

    if (hasil.ditutup && o.benar !== null && o.benar !== undefined) {
      isiBar.classList.toggle("benar", !!o.benar);
      isiBar.classList.toggle("salah", !o.benar);
      isiBar.classList.remove("teratas");
      const label = baris.querySelector(".bar-label");
      if (o.benar && !label.dataset.ditandai) {
        label.dataset.ditandai = "1";
        label.innerHTML = `${escapeHtml(o.teks)} <span class="chip chip-benar" style="margin-left:6px">Benar</span>`;
      }
    }

    aturLebar(isiBar, o.persen);
    const angka = baris.querySelector(".bar-angka");
    animasiAngka(angka, o.persen, { akhiran: "%", desimal: o.persen % 1 ? 1 : 0 });
  });
}

/* ------------------------------------------------ Hasil: Word Cloud ----- */

function gambarWordCloud(hasil) {
  const wadah = $("#wadah-hasil");
  if (!wadah) return;
  let awan = wadah.querySelector(".awan-kata");
  if (!awan) {
    awan = document.createElement("div");
    awan.className = "awan-kata";
    wadah.appendChild(awan);
  }
  if (!hasil.kata.length) {
    awan.innerHTML = '<div class="kosong">Menunggu jawaban disetujui presenter…</div>';
    return;
  }
  const maks = Math.max(...hasil.kata.map((k) => k.jumlah), 1);
  const terlihat = new Set();

  hasil.kata.forEach((k, i) => {
    const kunci = k.teks.toLowerCase();
    terlihat.add(kunci);
    let span = awan.querySelector(`[data-kata="${CSS.escape(kunci)}"]`);
    if (!span) {
      span = document.createElement("span");
      span.className = "kata";
      span.dataset.kata = kunci;
      span.textContent = k.teks;
      awan.appendChild(span);
    }
    // Ukuran mengikuti akar dari frekuensi supaya selisihnya tidak ekstrem.
    const skala = Math.sqrt(k.jumlah / maks);
    span.style.fontSize = `${Math.round(18 + skala * 46)}px`;
    span.classList.toggle("puncak", i < 3);
    span.title = `${k.teks} — ${k.jumlah}×`;
  });

  awan.querySelectorAll(".kata").forEach((span) => {
    if (!terlihat.has(span.dataset.kata)) span.remove();
  });
  const kosong = awan.querySelector(".kosong");
  if (kosong) kosong.remove();
}

/* ---------------------------------------------------- Hasil: Rating ----- */

function gambarRating(hasil) {
  const wadah = $("#wadah-hasil");
  if (!wadah) return;
  let panel = wadah.querySelector(".panel-rating");
  if (!panel) {
    panel = document.createElement("div");
    panel.className = "panel-rating";
    panel.innerHTML = `
      <div class="baris antara mb-24" style="align-items:baseline">
        <div><span class="angka-besar" id="rating-rata">0</span>
        <span class="muted"> dari ${hasil.rating.maks}</span></div>
        <span class="chip chip-aksen">Rata-rata</span>
      </div>
      <div id="rating-bar"></div>`;
    wadah.appendChild(panel);
  }
  animasiAngka($("#rating-rata"), hasil.rating.rata, { desimal: 2 });

  const total = hasil.rating.distribusi.reduce((a, b) => a + b.jumlah, 0) || 1;
  const puncak = Math.max(...hasil.rating.distribusi.map((d) => d.jumlah), 0);
  const bar = $("#rating-bar");
  hasil.rating.distribusi.forEach((d) => {
    let baris = bar.querySelector(`[data-nilai="${d.nilai}"]`);
    if (!baris) {
      baris = document.createElement("div");
      baris.className = "bar-baris";
      baris.dataset.nilai = String(d.nilai);
      baris.innerHTML = `
        <div class="bar-label">Nilai ${d.nilai}</div>
        <div class="bar-jalur"><div class="bar-isi"></div></div>
        <div class="bar-angka"></div>`;
      bar.appendChild(baris);
    }
    const persen = (d.jumlah * 100) / total;
    const isiBar = baris.querySelector(".bar-isi");
    isiBar.classList.toggle("teratas", d.jumlah > 0 && d.jumlah === puncak);
    aturLebar(isiBar, persen);
    animasiAngka(baris.querySelector(".bar-angka"), d.jumlah, { akhiran: "×" });
  });
}

/* ------------------------------------------------------- Moderasi ------- */

function gambarModerasi(moderasi) {
  const kartu = $("#kartu-moderasi");
  if (!moderasi) {
    kartu.classList.add("sembunyi");
    rapikanKolom();
    return;
  }
  kartu.classList.remove("sembunyi");
  rapikanKolom();
  $("#jumlah-pending").textContent = `${moderasi.jumlah} PENDING`;

  const wadah = $("#antrian-kata");
  const adaSekarang = new Set(moderasi.antrian.map((a) => String(a.participant_id)));

  // Item yang sudah dimoderasi keluar dengan animasi, tidak langsung hilang.
  $$(".antrian-item", wadah).forEach((el) => {
    if (!adaSekarang.has(el.dataset.pid) && !el.classList.contains("keluar")) {
      el.classList.add("keluar");
      const buang = () => {
        if (!el.isConnected) return;
        el.remove();
        perbaruiKosong(wadah);
      };
      el.addEventListener("animationend", buang, { once: true });
      // Jaring pengaman: tanpa ini item bisa tertinggal di antrian kalau
      // animasi keluar tidak pernah dijalankan browser.
      setTimeout(buang, 320);
    }
  });

  moderasi.antrian.forEach((item) => {
    if (wadah.querySelector(`[data-pid="${item.participant_id}"]`)) return;
    const el = document.createElement("div");
    el.className = "antrian-item";
    el.dataset.pid = String(item.participant_id);
    el.innerHTML = `
      <span style="overflow-wrap:anywhere">${escapeHtml(item.teks)}</span>
      <span class="baris baris-rapat">
        <button class="btn btn-ikon btn-utama" data-aksi="approve" title="Setujui">✓</button>
        <button class="btn btn-ikon btn-garis" data-aksi="reject" title="Tolak">✕</button>
      </span>`;
    el.addEventListener("click", async (ev) => {
      const tombol = ev.target.closest("[data-aksi]");
      if (!tombol) return;
      tombol.disabled = true;
      try {
        await api(`/api/admin/sesi/${KODE}/moderasi`, {
          method: "POST",
          body: { participant_id: item.participant_id, aksi: tombol.dataset.aksi },
        });
      } catch (err) {
        toast(err.message, "galat");
        tombol.disabled = false;
      }
    });
    wadah.appendChild(el);
  });

  perbaruiKosong(wadah);
}

/** Tampilkan/lepas placeholder "tidak ada antrian" sesuai isi antrian saat ini. */
function perbaruiKosong(wadah) {
  const adaItem = wadah.querySelector(".antrian-item:not(.keluar)");
  const kosong = wadah.querySelector(".kosong");
  if (adaItem && kosong) kosong.remove();
  if (!adaItem && !kosong) {
    const el = document.createElement("div");
    el.className = "kosong";
    el.style.padding = "22px";
    el.textContent = "Tidak ada antrian";
    wadah.appendChild(el);
  }
}

/* ----------------------------------------------------- Leaderboard ------ */

const MEDALI = { 1: "🥇", 2: "🥈", 3: "🥉" };

/** Leaderboard sebagai panel utama penuh (bukan sidebar) — dipanggil lewat tombol "Lihat Leaderboard". */
function gambarPapanUtama(papan) {
  idPertanyaanTampil = null;
  tipeTampil = null;
  timer.sembunyikan();
  gantiTampilan(isi, () => {
    const el = document.createElement("div");
    el.innerHTML = `
      <div class="chip chip-aksen mb-16">Leaderboard</div>
      <div id="papan-utama-isi"></div>`;
    return el;
  }).then(() => isiPapanUtama(papan));
}

/** Isi ulang daftar leaderboard di panel utama, dengan animasi FLIP untuk baris yang pindah posisi. */
function isiPapanUtama(papan) {
  const wadah = $("#papan-utama-isi");
  if (!wadah || !papan) return;
  if (!papan.baris.length) {
    wadah.innerHTML = '<div class="kosong">Belum ada skor</div>';
    skalakanPapanUtama();
    sesuaikanUkuranPanggung();
    return;
  }
  const kosong = wadah.querySelector(".kosong");
  if (kosong) kosong.remove();

  const sebelum = rekamPosisi($$(".papan-baris", wadah));
  const urut = [];
  papan.baris.forEach((b) => {
    let el = wadah.querySelector(`[data-kunci="${b.participant_id}"]`);
    if (!el) {
      el = document.createElement("div");
      el.className = "papan-baris besar";
      el.dataset.kunci = String(b.participant_id);
      el.innerHTML = `<span class="papan-peringkat"></span><span class="papan-nama"></span><span class="papan-poin"></span>`;
      el.style.opacity = "0";
      requestAnimationFrame(() => (el.style.opacity = "1"));
    }
    el.classList.toggle("juara", b.peringkat === 1);
    el.querySelector(".papan-peringkat").textContent = MEDALI[b.peringkat] || b.peringkat;
    el.querySelector(".papan-nama").textContent = b.nickname;
    animasiAngka(el.querySelector(".papan-poin"), b.poin);
    urut.push(el);
  });
  urut.forEach((el) => wadah.appendChild(el));
  $$(".papan-baris", wadah).forEach((el) => {
    if (!urut.includes(el)) el.remove();
  });
  mainkanFlip(urut, sebelum);
  skalakanPapanUtama();
  sesuaikanUkuranPanggung();
}

/** Simpan leaderboard terbaru dan aktifkan/nonaktifkan tombol sesuai ketersediaan data. */
function catatPapan(papan) {
  papanTerakhir = papan || null;
  const tombol = $("#btn-papan");
  if (!tombol) return;
  tombol.disabled = !papanTerakhir;
  if (modeTampilan === "leaderboard") isiPapanUtama(papanTerakhir);
}

/* ---------------------------------------------------------- Terapkan ---- */

/** Kolom samping dilipat kalau tidak ada kartu yang perlu ditampilkan. */
function rapikanKolom() {
  const samping = $("#samping");
  const adaIsi = $$(".kartu", samping).some((k) => !k.classList.contains("sembunyi"));
  samping.classList.toggle("sembunyi", !adaIsi);
  const panggung = $("#panggung");
  panggung.classList.toggle("tanpa-samping", !adaIsi);

  // Layar lobi (QR kiri, peserta gabung kanan, 50/50) hanya berlaku selama
  // kartu peserta itu satu-satunya yang tampil di kolom samping — begitu
  // soal dibuka atau sesi berakhir, kartu itu disembunyikan dan layar balik
  // ke proporsi sidebar biasa.
  const kartuPeserta = $("#kartu-peserta-lobi");
  const tampilanLobi = !!(kartuPeserta && !kartuPeserta.classList.contains("sembunyi"));
  panggung.classList.toggle("tampilan-lobi", tampilanLobi);
  if (tampilanLobi) sesuaikanLobi();
}

/* --------------------------------------------- Tahap "belum dibuka" ----- */

/** Layar penantian: pertanyaan tetap besar, hasil belum digambar. */
function gambarMenunggu(hasil) {
  const wadah = $("#wadah-hasil");
  if (!wadah) return;
  const butuh = ambangJawaban();
  const masuk = hasil.total_jawaban;

  let panel = wadah.querySelector(".menunggu-hasil");
  if (!panel) {
    wadah.replaceChildren();
    panel = document.createElement("div");
    panel.className = "menunggu-hasil";
    panel.innerHTML = `
      <div class="menunggu-angka">
        <span id="menunggu-jumlah">0</span><span class="menunggu-total"></span>
      </div>
      <div class="bar-jalur tinggi"><div class="bar-isi teratas"></div></div>
      <p class="muted mt-16" id="menunggu-teks"></p>
      <button class="btn btn-garis btn-kecil mt-8" id="btn-buka-hasil">Tampilkan Hasil Sekarang</button>`;
    wadah.appendChild(panel);
    $("#btn-buka-hasil").addEventListener("click", () => {
      bukaHasil();
      terapkanHasil(hasilTerakhir);
    });
  }

  animasiAngka($("#menunggu-jumlah"), masuk);
  panel.querySelector(".menunggu-total").textContent =
    puncakOnline ? ` / ${puncakOnline} partisipan` : " jawaban masuk";
  aturLebar(panel.querySelector(".bar-isi"), Math.min(100, (masuk * 100) / butuh));
  $("#menunggu-teks").textContent =
    masuk >= butuh
      ? "Menyiapkan hasil…"
      : `Hasil muncul otomatis setelah ${butuh} partisipan menjawab`;
}

/**
 * Quiz Mode: selama timer berjalan layar hanya menampilkan pilihan jawabannya,
 * tanpa angka sama sekali. Kalau distribusi ditampilkan lebih dulu, peserta
 * yang belum menjawab tinggal ikut suara terbanyak — persis yang dihindari
 * kuis bergaya Kahoot.
 */
function gambarOpsiKuis(hasil) {
  const wadah = $("#wadah-hasil");
  if (!wadah) return;

  let panel = wadah.querySelector(".opsi-papan");
  if (!panel) {
    wadah.replaceChildren();
    panel = document.createElement("div");
    panel.className = "opsi-papan";
    const grid = document.createElement("div");
    grid.className = `kuis-grid papan${adaOpsiPanjang(hasil.opsi) ? " satu-kolom" : ""}`;
    hasil.opsi.forEach((o, i) => {
      const kotak = document.createElement("div");
      kotak.className = `kuis-kotak papan ${KELAS_OPSI[i % KELAS_OPSI.length]}`;
      kotak.textContent = o.teks;
      grid.appendChild(kotak);
      // Kotak jawaban masuk satu per satu (bukan cuma ikut fade seluruh
      // panel dari gantiTampilan) — supaya transisi dari hitung mundur ke
      // pilihan jawaban kerasa hidup/smooth, bukan seperti layar "refresh"
      // tiba-tiba berganti isi.
      if (!gerakDikurangi()) {
        kotak.animate(
          [{ opacity: 0, transform: "translateY(14px) scale(0.96)" }, { opacity: 1, transform: "none" }],
          { duration: 340, delay: i * 70, easing: "cubic-bezier(0.34,1.56,0.64,1)", fill: "backwards" }
        );
      }
    });
    panel.appendChild(grid);
    const kaki = document.createElement("div");
    kaki.className = "tengah mt-24";
    kaki.innerHTML = '<span class="chip" id="hitung-jawab">0 sudah menjawab</span>';
    panel.appendChild(kaki);
    wadah.appendChild(panel);
  }

  const label = $("#hitung-jawab");
  if (label) {
    label.textContent = puncakOnline
      ? `${hasil.total_jawaban} dari ${puncakOnline} sudah menjawab`
      : `${hasil.total_jawaban} sudah menjawab`;
  }
}

/** Lepas panel penantian; grafik digambar ulang dari kosong agar ikut beranimasi. */
function bukaHasil() {
  if (hasilTerbuka) return;
  hasilTerbuka = true;
  const wadah = $("#wadah-hasil");
  if (wadah) wadah.replaceChildren();
}

let hasilTerakhir = null;

function terapkanHasil(hasil) {
  if (!hasil) return;
  hasilTerakhir = hasil;
  const ringkas = $("#ringkas-jawaban");
  if (ringkas) {
    const n = hasil.total_jawaban;
    // Saat soal quiz berjalan, hitungannya sudah tampil di chip bawah kotak
    // jawaban — tidak perlu diulang di subjudul.
    ringkas.textContent =
      KUIS && !hasil.ditutup
        ? ""
        : `${n} partisipan telah menjawab${hasil.ditutup ? " · soal ditutup" : ""}`;
  }

  if (!hasilTerbuka) {
    if (KUIS) {
      // Quiz Mode: distribusi baru boleh muncul setelah soal ditutup.
      if (hasil.ditutup) bukaHasil();
      else {
        gambarOpsiKuis(hasil);
        sesuaikanUkuranPanggung();
        return;
      }
    } else {
      // Word cloud terbuka begitu presenter menyetujui kata pertama — approve
      // itu sendiri sudah tindakan sadar presenter, tidak perlu digerbang dua kali.
      const lewatAmbang = hasil.total_jawaban >= ambangJawaban();
      const adaKataDisetujui = hasil.tipe === "word_cloud" && hasil.kata.length > 0;
      if (hasil.ditutup || lewatAmbang || adaKataDisetujui) bukaHasil();
      else {
        gambarMenunggu(hasil);
        sesuaikanUkuranPanggung();
        return;
      }
    }
  }

  if (hasil.tipe === "mc") gambarHasilMC(hasil);
  else if (hasil.tipe === "word_cloud") gambarWordCloud(hasil);
  else if (hasil.tipe === "rating") gambarRating(hasil);
  sesuaikanUkuranPanggung();
}

function terapkanPertanyaan(pertanyaan, hasil, moderasi, baruDibuka = false) {
  if (!pertanyaan) {
    gambarLobi();
    gambarModerasi(null);
    $("#btn-tutup").disabled = true;
    const tombolBerikutnya = $("#btn-berikutnya");
    if (tombolBerikutnya) tombolBerikutnya.textContent = "Mulai →";
    return;
  }
  const kartuPeserta = $("#kartu-peserta-lobi");
  if (kartuPeserta && !kartuPeserta.classList.contains("sembunyi")) {
    kartuPeserta.classList.add("sembunyi");
    rapikanKolom();
  }
  pertanyaanTerakhir = pertanyaan;
  // Soal yang dibuka ulang memulai pengumpulan dari nol, jadi gerbang hasil
  // ikut ditutup lagi walau kerangka di layar tidak berubah — leaderboard
  // soal sebelumnya juga tidak relevan lagi sampai soal ini ditutup.
  if (baruDibuka) {
    batalkanLeaderboardOtomatis();
    hasilTerbuka = false;
    modeTampilan = "hasil";
    const tombolPapan = $("#btn-papan");
    if (tombolPapan) {
      tombolPapan.textContent = "Lihat Leaderboard →";
      tombolPapan.disabled = true;
    }
  }
  if (modeTampilan === "leaderboard") {
    // Presenter sedang melihat leaderboard — konten hasil ditahan (jangan
    // ditimpa), tapi status tombol/timer TETAP harus ikut kondisi soal yang
    // sebenarnya (dulu early return di sini bikin timer & #btn-tutup macet
    // di kondisi lama selama leaderboard terbuka, termasuk saat soal ditutup
    // sementara presenter sedang melihat leaderboard).
    hasilTerakhir = hasil;
    sinkronkanKontrolSoal(pertanyaan);
    return;
  }
  if (baruDibuka || pertanyaan.id !== idPertanyaanTampil || pertanyaan.tipe !== tipeTampil) {
    // Isi hasil tepat setelah kerangka terpasang, bukan setelah jeda tebakan.
    gambarKerangka(pertanyaan).then(() => {
      terapkanHasil(hasil);
      if (pertanyaan.tipe === "word_cloud") gambarModerasi(moderasi || { antrian: [], jumlah: 0 });
      else gambarModerasi(null);
    });
  } else {
    terapkanHasil(hasil);
    if (pertanyaan.tipe === "word_cloud" && moderasi) gambarModerasi(moderasi);
  }

  sinkronkanKontrolSoal(pertanyaan);
}

/** Timer & tombol "Tutup Soal" harus selalu mengikuti kondisi soal yang
    sebenarnya, terlepas dari layar mana yang sedang ditampilkan presenter. */
function sinkronkanKontrolSoal(pertanyaan) {
  $("#btn-tutup").disabled = !!pertanyaan.ditutup;
  if (MODE === "quiz" && !pertanyaan.ditutup && pertanyaan.sisa_ms != null) {
    timer.mulai(pertanyaan.sisa_ms, pertanyaan.durasi);
  } else {
    timer.sembunyikan();
  }
  // Soal terakhir: klik tombol ini sebenarnya mengakhiri sesi (lihat
  // handler #btn-berikutnya — hasil.habis memicu /akhiri otomatis), jadi
  // labelnya diganti supaya presenter tahu apa yang bakal terjadi.
  const tombolBerikutnya = $("#btn-berikutnya");
  if (tombolBerikutnya) {
    const soalTerakhir = pertanyaan.total_soal != null && pertanyaan.urutan_ke >= pertanyaan.total_soal;
    tombolBerikutnya.textContent = soalTerakhir ? "Lihat Hasil →" : "Soal Berikutnya →";
  }
}

/* ------------------------------------------------------------ Soket ----- */

const soket = new KlienSoket(`/ws/present/${KODE}`, {
  saatPesan(pesan) {
    switch (pesan.tipe) {
      case "state":
      case "pertanyaan_dibuka":
        if (pesan.tipe === "pertanyaan_dibuka") puncakOnline = 0;
        if (pesan.sesi) catatOnline(pesan.sesi.online ?? 0);
        if (Array.isArray(pesan.peserta)) {
          pesan.peserta.forEach((p) => pesertaGabung.set(p.participant_id, p.nickname));
        }
        terapkanPertanyaan(
          pesan.pertanyaan,
          pesan.hasil,
          pesan.moderasi,
          pesan.tipe === "pertanyaan_dibuka"
        );
        catatPapan(pesan.leaderboard);
        break;
      case "sesi_diubah":
        if (pesan.sesi && pesan.sesi.judul) {
          const judul = $("#judul-panggung");
          if (judul) judul.textContent = pesan.sesi.judul;
        }
        break;
      case "peserta_gabung":
        tambahPesertaLobi(pesan.participant_id, pesan.nickname);
        break;
      case "hitung_mundur":
        if (pesan.sesi) catatOnline(pesan.sesi.online ?? 0);
        gambarHitungMundur(pesan.pertanyaan, pesan.detik);
        break;
      case "hasil":
        catatOnline(pesan.online);
        terapkanHasil(pesan.hasil);
        break;
      case "moderasi":
        gambarModerasi(pesan);
        break;
      case "online":
        catatOnline(pesan.jumlah);
        break;
      case "pertanyaan_ditutup":
        timer.sembunyikan();
        terapkanPertanyaan(pesan.pertanyaan, pesan.hasil, null);
        catatPapan(pesan.leaderboard);
        toast(pesan.alasan === "timer" ? "Waktu habis — soal ditutup" : "Soal ditutup");
        // Grafik hasil tampil dulu, lalu leaderboard muncul sendiri 3 detik
        // kemudian — presenter tetap bisa buka manual lebih cepat, atau
        // batal otomatis kalau keburu pindah soal.
        batalkanLeaderboardOtomatis();
        if (KUIS) timerLeaderboardOtomatis = setTimeout(bukaLeaderboard, 3000);
        break;
      case "sesi_selesai":
        // Sesi benar-benar berakhir — selalu tampilkan layar penutup,
        // menimpa apa pun yang sedang dilihat presenter saat itu.
        gambarSesiSelesai(pesan.sesi, pesan.leaderboard);
        toast("Sesi telah berakhir");
        // Sesi sudah ditutup — berhenti mencoba menyambung ulang.
        soket.tutup();
        break;
      case "sesi_tidak_ada":
        isi.innerHTML = '<div class="kosong">Sesi tidak aktif. Buka halaman kelola untuk memeriksa.</div>';
        soket.tutup();
        break;
    }
  },
});
soket.sambung();
rapikanKolom();

/* ----------------------------------------------------------- Kontrol ---- */

$("#btn-tutup").addEventListener("click", async (e) => {
  e.currentTarget.disabled = true;
  try {
    await api(`/api/admin/sesi/${KODE}/tutup`, { method: "POST" });
  } catch (err) {
    toast(err.message, "galat");
    e.currentTarget.disabled = false;
  }
});

$("#btn-berikutnya").addEventListener("click", async (e) => {
  const tombol = e.currentTarget;
  tombol.disabled = true;
  try {
    const hasil = await api(`/api/admin/sesi/${KODE}/berikutnya`, { method: "POST" });
    // Sudah di soal terakhir — langsung akhiri sesi supaya leaderboard/podium
    // tampil otomatis, tidak perlu klik "Akhiri Sesi" terpisah lagi.
    if (hasil && hasil.habis) await api(`/api/admin/sesi/${KODE}/akhiri`, { method: "POST" });
  } catch (err) {
    toast(err.message, "galat");
  } finally {
    tombol.disabled = false;
  }
});

$("#btn-approve-semua").addEventListener("click", async () => {
  try {
    const hasil = await api(`/api/admin/sesi/${KODE}/moderasi-semua`, { method: "POST", body: { aksi: "approve" } });
    toast(`${hasil.jumlah} jawaban disetujui`, "sukses");
  } catch (err) {
    toast(err.message, "galat");
  }
});

$("#btn-reject-semua").addEventListener("click", async () => {
  try {
    const hasil = await api(`/api/admin/sesi/${KODE}/moderasi-semua`, { method: "POST", body: { aksi: "reject" } });
    toast(`${hasil.jumlah} jawaban ditolak`);
  } catch (err) {
    toast(err.message, "galat");
  }
});

const btnPapan = $("#btn-papan");

/** Balik dari leaderboard ke grafik hasil soal terakhir (dipanggil dari tombol). */
function tutupLeaderboard() {
  batalkanLeaderboardOtomatis();
  modeTampilan = "hasil";
  if (btnPapan) btnPapan.textContent = "Lihat Leaderboard →";
  if (pertanyaanTerakhir) {
    gambarKerangka(pertanyaanTerakhir).then(() => {
      terapkanHasil(hasilTerakhir);
      if (pertanyaanTerakhir.tipe === "word_cloud") gambarModerasi({ antrian: [], jumlah: 0 });
    });
    // Timer/#btn-tutup ikut disegarkan — soal bisa saja sudah tertutup
    // (timer habis atau presenter menutupnya) selagi leaderboard terbuka.
    sinkronkanKontrolSoal(pertanyaanTerakhir);
  }
}

/** Tampilkan panel leaderboard penuh — dipanggil dari tombol ATAU otomatis 3 detik setelah hasil. */
function bukaLeaderboard() {
  batalkanLeaderboardOtomatis();
  if (modeTampilan === "leaderboard" || !papanTerakhir) return;
  modeTampilan = "leaderboard";
  if (btnPapan) btnPapan.textContent = "← Kembali ke Hasil";
  gambarPapanUtama(papanTerakhir);
}

if (btnPapan) {
  btnPapan.addEventListener("click", () => {
    if (modeTampilan === "leaderboard") tutupLeaderboard();
    else bukaLeaderboard();
  });
}

$("#btn-layar-penuh").addEventListener("click", () => {
  if (document.fullscreenElement) document.exitFullscreen();
  else document.documentElement.requestFullscreen().catch(() => {});
});

// Pintasan keyboard untuk presenter: spasi = soal berikutnya, X = tutup soal.
document.addEventListener("keydown", (e) => {
  if (e.target.matches("input, textarea")) return;
  if (e.code === "Space") {
    e.preventDefault();
    $("#btn-berikutnya").click();
  } else if (e.key.toLowerCase() === "x") {
    if (!$("#btn-tutup").disabled) $("#btn-tutup").click();
  }
});
