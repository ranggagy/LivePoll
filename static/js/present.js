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
  CincinTimer,
  KlienSoket,
  KELAS_OPSI,
} from "./common.js";

const akar = document.querySelector("[data-kode]");
const KODE = akar.dataset.kode;
const MODE = akar.dataset.mode;
const TAUTAN = akar.dataset.tautan;

const isi = $("#isi-panggung");
const timer = new CincinTimer($("#timer"));

let idPertanyaanTampil = null;
let tipeTampil = null;

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

const escapeHtml = (t) =>
  String(t ?? "").replace(/[&<>"']/g, (c) =>
    ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c])
  );

/* ------------------------------------------------------------- Lobi ----- */

function gambarLobi() {
  idPertanyaanTampil = null;
  tipeTampil = null;
  timer.sembunyikan();
  gantiTampilan(isi, () => {
    const el = document.createElement("div");
    el.innerHTML = `
      <div class="qr-kotak">
        <img src="/qr/${KODE}.svg" alt="QR code untuk bergabung ke sesi ${KODE}" width="168" height="168">
        <div class="tumbuh">
          <div class="muted mb-8">Buka di HP lalu masukkan kode</div>
          <div class="kode-raksasa">${KODE}</div>
          <div class="muted mt-8" style="overflow-wrap:anywhere">${escapeHtml(TAUTAN)}</div>
        </div>
      </div>
      <p class="muted mt-24">Belum ada pertanyaan yang dibuka. Klik “Soal Berikutnya” untuk memulai.</p>`;
    return el;
  });
}

/** Layar penutup: sesi sudah berakhir, hasil akhir tetap bisa dilihat. */
function gambarSesiSelesai(sesi) {
  timer.sembunyikan();
  gantiTampilan(isi, () => {
    const el = document.createElement("div");
    el.className = "tengah";
    el.innerHTML = `
      <div class="lencana-hasil">✓</div>
      <h2 style="font-size:22px">Sesi telah berakhir</h2>
      <p class="muted mt-8">${escapeHtml((sesi && sesi.judul) || "")}</p>
      <p class="muted mt-16">Hasil akhir masih bisa diunduh lewat tombol Export Excel.</p>`;
    return el;
  });
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
      <div class="pertanyaan-besar">${escapeHtml(pertanyaan.teks)}</div>
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

  hasil.opsi.forEach((o) => {
    let baris = wadah.querySelector(`[data-opsi="${o.id}"]`);
    if (!baris) {
      baris = document.createElement("div");
      baris.className = "bar-baris";
      baris.dataset.opsi = String(o.id);
      baris.innerHTML = `
        <div class="bar-label"></div>
        <div class="bar-jalur"><div class="bar-isi"></div></div>
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
        label.innerHTML = `${escapeHtml(o.teks)} <span class="chip chip-aksen" style="margin-left:6px">Benar</span>`;
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

function gambarPapan(papan) {
  if (!papan || !papan.baris) return;
  $("#kartu-papan").classList.remove("sembunyi");
  rapikanKolom();
  const wadah = $("#papan-isi");
  if (!papan.baris.length) {
    wadah.innerHTML = '<div class="kosong">Belum ada skor</div>';
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
      el.className = "papan-baris";
      el.dataset.kunci = String(b.participant_id);
      el.innerHTML = `<span class="papan-peringkat"></span><span class="papan-nama"></span><span class="papan-poin"></span>`;
      el.style.opacity = "0";
      requestAnimationFrame(() => (el.style.opacity = "1"));
    }
    el.classList.toggle("juara", b.peringkat === 1);
    el.querySelector(".papan-peringkat").textContent = b.peringkat;
    el.querySelector(".papan-nama").textContent = b.nickname;
    animasiAngka(el.querySelector(".papan-poin"), b.poin);
    urut.push(el);
  });
  urut.forEach((el) => wadah.appendChild(el));
  $$(".papan-baris", wadah).forEach((el) => {
    if (!urut.includes(el)) el.remove();
  });
  mainkanFlip(urut, sebelum);
}

/* ---------------------------------------------------------- Terapkan ---- */

/** Kolom samping dilipat kalau tidak ada kartu yang perlu ditampilkan. */
function rapikanKolom() {
  const samping = $("#samping");
  const adaIsi = $$(".kartu", samping).some((k) => !k.classList.contains("sembunyi"));
  samping.classList.toggle("sembunyi", !adaIsi);
  $("#panggung").classList.toggle("tanpa-samping", !adaIsi);
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
    grid.className = "kuis-grid papan";
    hasil.opsi.forEach((o, i) => {
      const kotak = document.createElement("div");
      kotak.className = `kuis-kotak papan ${KELAS_OPSI[i % KELAS_OPSI.length]}`;
      kotak.textContent = o.teks;
      grid.appendChild(kotak);
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
      else return gambarOpsiKuis(hasil);
    } else {
      // Word cloud terbuka begitu presenter menyetujui kata pertama — approve
      // itu sendiri sudah tindakan sadar presenter, tidak perlu digerbang dua kali.
      const lewatAmbang = hasil.total_jawaban >= ambangJawaban();
      const adaKataDisetujui = hasil.tipe === "word_cloud" && hasil.kata.length > 0;
      if (hasil.ditutup || lewatAmbang || adaKataDisetujui) bukaHasil();
      else return gambarMenunggu(hasil);
    }
  }

  if (hasil.tipe === "mc") gambarHasilMC(hasil);
  else if (hasil.tipe === "word_cloud") gambarWordCloud(hasil);
  else if (hasil.tipe === "rating") gambarRating(hasil);
}

function terapkanPertanyaan(pertanyaan, hasil, moderasi, baruDibuka = false) {
  if (!pertanyaan) {
    gambarLobi();
    gambarModerasi(null);
    $("#btn-tutup").disabled = true;
    return;
  }
  // Soal yang dibuka ulang memulai pengumpulan dari nol, jadi gerbang hasil
  // ikut ditutup lagi walau kerangka di layar tidak berubah.
  if (baruDibuka) hasilTerbuka = false;
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

  $("#btn-tutup").disabled = !!pertanyaan.ditutup;
  if (MODE === "quiz" && !pertanyaan.ditutup && pertanyaan.sisa_ms != null) {
    timer.mulai(pertanyaan.sisa_ms, pertanyaan.durasi);
  } else {
    timer.sembunyikan();
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
        terapkanPertanyaan(
          pesan.pertanyaan,
          pesan.hasil,
          pesan.moderasi,
          pesan.tipe === "pertanyaan_dibuka"
        );
        gambarPapan(pesan.leaderboard);
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
        gambarPapan(pesan.leaderboard);
        toast(pesan.alasan === "timer" ? "Waktu habis — soal ditutup" : "Soal ditutup");
        break;
      case "sesi_selesai":
        timer.sembunyikan();
        // Kalau tidak ada soal yang sedang tampil (mis. halaman baru
        // di-refresh setelah acara), tampilkan layar penutup.
        if (idPertanyaanTampil === null) gambarSesiSelesai(pesan.sesi);
        gambarPapan(pesan.leaderboard);
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
    if (hasil && hasil.habis) toast("Sudah di pertanyaan terakhir");
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
