/* Utilitas bersama: pemanggilan API, toast, animasi angka, FLIP, timer,
   dan klien WebSocket dengan auto-reconnect. */

export const $ = (sel, akar = document) => akar.querySelector(sel);
export const $$ = (sel, akar = document) => Array.from(akar.querySelectorAll(sel));

export const escapeHtml = (t) =>
  String(t ?? "").replace(/[&<>"']/g, (c) =>
    ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c])
  );

export const gerakDikurangi = () =>
  window.matchMedia("(prefers-reduced-motion: reduce)").matches;

/* ---------------------------------------------------------------- API --- */

export async function api(url, opsi = {}) {
  const resp = await fetch(url, {
    headers: { "Content-Type": "application/json" },
    ...opsi,
    body: opsi.body ? JSON.stringify(opsi.body) : undefined,
  });
  let data = null;
  const tipe = resp.headers.get("content-type") || "";
  if (tipe.includes("application/json")) data = await resp.json();
  if (!resp.ok) {
    const pesan = (data && (data.detail || data.pesan)) || `Gagal (${resp.status})`;
    throw new Error(typeof pesan === "string" ? pesan : "Permintaan gagal");
  }
  return data;
}

/* -------------------------------------------------------------- Toast --- */

let tumpukanToast = null;

export function toast(pesan, jenis = "") {
  if (!tumpukanToast) {
    tumpukanToast = document.createElement("div");
    tumpukanToast.className = "toast-tumpuk";
    document.body.appendChild(tumpukanToast);
  }
  const el = document.createElement("div");
  el.className = `toast ${jenis}`;
  el.textContent = pesan;
  tumpukanToast.appendChild(el);
  setTimeout(() => {
    el.classList.add("pergi");
    el.addEventListener("animationend", () => el.remove(), { once: true });
  }, 2800);
}

/* ------------------------------------------------------ Animasi angka --- */

/**
 * Hitung naik/turun sebuah angka dengan easing.
 *
 * Animasinya pakai requestAnimationFrame, tapi nilai akhirnya TIDAK boleh
 * bergantung pada rAF: di tab latar — dan di panel pratinjau yang tidak
 * digambar walau `document.hidden` tetap false — rAF berhenti dipanggil dan
 * angka akan membeku di nilai lama. Karena itu ada jaring pengaman setTimeout
 * yang menuliskan nilai akhir apa pun yang terjadi.
 */
export function animasiAngka(el, target, { durasi = 700, awalan = "", akhiran = "", desimal = 0 } = {}) {
  const mulai = Number(el.dataset.nilai || 0);
  const selisih = target - mulai;
  el.dataset.nilai = String(target);
  if (selisih === 0 && el.textContent) return;

  const tulis = (n) => {
    el.textContent = awalan + n.toFixed(desimal) + akhiran;
  };

  if (gerakDikurangi() || durasi === 0) {
    tulis(target);
    return;
  }

  if (el._animasi) cancelAnimationFrame(el._animasi);
  clearTimeout(el._jaring);
  el._jaring = setTimeout(() => {
    // Hanya menyusul kalau target belum berubah lagi sejak jaring dipasang.
    if (el.dataset.nilai === String(target)) tulis(target);
  }, durasi + 80);

  const t0 = performance.now();
  const langkah = (t) => {
    const p = Math.min((t - t0) / durasi, 1);
    // easeOutCubic — cepat di awal, melambat halus di akhir.
    const e = 1 - Math.pow(1 - p, 3);
    tulis(mulai + selisih * e);
    if (p < 1) {
      el._animasi = requestAnimationFrame(langkah);
    } else {
      el._animasi = null;
      clearTimeout(el._jaring);
    }
  };
  el._animasi = requestAnimationFrame(langkah);
}

/**
 * Set lebar bar hasil. Nilai akhir ditulis langsung (bukan lewat rAF) supaya
 * bar tidak tertinggal di 0% ketika update datang saat tab tidak terlihat;
 * animasinya tetap jalan karena transisi CSS punya titik awal 0% yang sudah
 * ter-commit lewat reflow paksa saat bar pertama kali dibuat.
 */
export function aturLebar(el, persen) {
  if (!el.dataset.siap) {
    el.style.width = "0%";
    void el.offsetWidth; // paksa reflow supaya transisi punya titik mulai
    el.dataset.siap = "1";
  }
  el.style.width = `${persen}%`;
}

/* ----------------------------------------------------------- FLIP ------- */

/** Rekam posisi elemen sebelum DOM berubah. */
export function rekamPosisi(elemen) {
  const peta = new Map();
  elemen.forEach((el) => {
    const kunci = el.dataset.kunci;
    if (kunci) peta.set(kunci, el.getBoundingClientRect().top);
  });
  return peta;
}

/** Setelah DOM berubah, geser elemen ke posisi lama lalu lepaskan (teknik FLIP). */
export function mainkanFlip(elemen, sebelum) {
  if (gerakDikurangi()) return;
  elemen.forEach((el) => {
    const kunci = el.dataset.kunci;
    if (!kunci || !sebelum.has(kunci)) return;
    const delta = sebelum.get(kunci) - el.getBoundingClientRect().top;
    if (!delta) return;
    el.style.transition = "none";
    el.style.transform = `translateY(${delta}px)`;
    const lepas = () => {
      el.style.transition = "";
      el.style.transform = "";
    };
    requestAnimationFrame(lepas);
    // Jaring pengaman: tanpa ini, baris bisa tertinggal tergeser kalau rAF
    // tidak pernah dipanggil (panel/tab tidak digambar).
    setTimeout(lepas, 60);
  });
}

/* --------------------------------------------------- Transisi tampilan -- */

/**
 * Ganti isi sebuah wadah dengan transisi keluar-masuk yang halus.
 * Mengembalikan Promise berisi elemen baru, supaya pemanggil bisa mengisi
 * kontennya tepat setelah terpasang — tanpa menebak-nebak durasi animasi.
 */
export function gantiTampilan(wadah, render) {
  const lama = wadah.firstElementChild;
  const pasang = () => {
    wadah.replaceChildren();
    const baru = render();
    if (baru) {
      baru.classList.add("tampilan");
      wadah.appendChild(baru);
    }
    return baru || null;
  };
  if (!lama || gerakDikurangi()) {
    return Promise.resolve(pasang());
  }
  lama.classList.add("keluar");
  return new Promise((selesaikan) => {
    let sudah = false;
    const lanjut = () => {
      if (sudah) return;
      sudah = true;
      selesaikan(pasang());
    };
    lama.addEventListener("animationend", lanjut, { once: true });
    // Jaring pengaman kalau animasi tidak pernah selesai (tab tersembunyi, dll).
    setTimeout(lanjut, 320);
  });
}

/* ---------------------------------------------------------- Timer ring -- */

/** Cincin countdown berbasis waktu server; digambar ulang tiap frame. */
export class CincinTimer {
  constructor(el) {
    this.el = el;
    this.el.innerHTML = `
      <svg viewBox="0 0 44 44" aria-hidden="true">
        <circle class="jalur" cx="22" cy="22" r="20"></circle>
        <circle class="maju" cx="22" cy="22" r="20"></circle>
      </svg>
      <div class="angka">--</div>`;
    this.maju = this.el.querySelector(".maju");
    this.angka = this.el.querySelector(".angka");
    this.keliling = 2 * Math.PI * 20;
    this.maju.style.strokeDasharray = String(this.keliling);
    this.maju.style.strokeDashoffset = "0";
    this._rafId = null;
  }

  /** Mulai hitung mundur; sisaMs berasal dari server, bukan dari jam client. */
  mulai(sisaMs, totalDetik, saatHabis) {
    this.hentikan();
    if (sisaMs == null || !totalDetik) {
      this.el.classList.add("sembunyi");
      return;
    }
    this.el.classList.remove("sembunyi");
    const totalMs = totalDetik * 1000;
    const berakhirPada = performance.now() + sisaMs;
    const gambar = (t) => {
      const sisa = Math.max(0, berakhirPada - t);
      const rasio = Math.min(1, sisa / totalMs);
      this.maju.style.strokeDashoffset = String(this.keliling * (1 - rasio));
      this.angka.textContent = String(Math.ceil(sisa / 1000));
      this.el.classList.toggle("mendesak", sisa <= 5000 && sisa > 0);
      if (sisa > 0) this._rafId = requestAnimationFrame(gambar);
      else {
        this._rafId = null;
        this.el.classList.remove("mendesak");
        if (saatHabis) saatHabis();
      }
    };
    this._rafId = requestAnimationFrame(gambar);
  }

  hentikan() {
    if (this._rafId) cancelAnimationFrame(this._rafId);
    this._rafId = null;
  }

  sembunyikan() {
    this.hentikan();
    this.el.classList.add("sembunyi");
  }
}

/* ------------------------------------------------------ Status koneksi -- */

export class IndikatorKoneksi {
  constructor() {
    this.el = document.createElement("div");
    this.el.className = "status-koneksi";
    this.el.innerHTML = `<span class="putar"></span><span class="teks">Menyambungkan ulang…</span>`;
    document.body.appendChild(this.el);
    this._timer = null;
  }
  tampilkan(teks = "Menyambungkan ulang…") {
    this.el.querySelector(".teks").textContent = teks;
    clearTimeout(this._timer);
    this.el.classList.add("tampil");
  }
  sembunyikan() {
    // Sedikit ditahan supaya tidak berkedip saat reconnect sangat cepat.
    clearTimeout(this._timer);
    this._timer = setTimeout(() => this.el.classList.remove("tampil"), 400);
  }
}

/* ---------------------------------------------------------- WebSocket --- */

/**
 * Klien WebSocket dengan auto-reconnect (backoff) dan heartbeat.
 * State sesi selalu diminta ulang ke server setiap kali koneksi pulih.
 */
export class KlienSoket {
  constructor(url, { saatPesan, saatBuka, saatTutup } = {}) {
    this.url = url;
    this.saatPesan = saatPesan || (() => {});
    this.saatBuka = saatBuka || (() => {});
    this.saatTutup = saatTutup || (() => {});
    this.ws = null;
    this.percobaan = 0;
    this.sengajaTutup = false;
    this.indikator = new IndikatorKoneksi();
    this._heartbeat = null;
    this._reconnect = null;
    this._antrian = [];

    // Browser kembali online / tab dibuka lagi → langsung coba sambung.
    window.addEventListener("online", () => this._sambungUlangSegera());
    document.addEventListener("visibilitychange", () => {
      if (!document.hidden) this._sambungUlangSegera();
    });
  }

  sambung() {
    this.sengajaTutup = false;
    const skema = location.protocol === "https:" ? "wss" : "ws";
    this.ws = new WebSocket(`${skema}://${location.host}${this.url}`);

    this.ws.onopen = () => {
      this.percobaan = 0;
      this.indikator.sembunyikan();
      this._mulaiHeartbeat();
      // Kirim ulang pesan yang sempat tertahan saat koneksi putus.
      const tertahan = this._antrian.splice(0);
      tertahan.forEach((p) => this.kirim(p));
      this.saatBuka();
      this.kirim({ tipe: "sinkron" });
    };

    this.ws.onmessage = (ev) => {
      let data;
      try {
        data = JSON.parse(ev.data);
      } catch {
        return;
      }
      if (data.tipe === "pong") return;
      this.saatPesan(data);
    };

    this.ws.onclose = () => {
      this._hentikanHeartbeat();
      this.saatTutup();
      if (this.sengajaTutup) return;
      this.indikator.tampilkan();
      this._jadwalkanSambungUlang();
    };

    this.ws.onerror = () => {
      try {
        this.ws.close();
      } catch {}
    };
  }

  _jadwalkanSambungUlang() {
    clearTimeout(this._reconnect);
    // Backoff 1s → 1.5s → 2.2s … maksimum 8 detik, plus jitter kecil.
    const jeda = Math.min(1000 * Math.pow(1.5, this.percobaan), 8000) + Math.random() * 400;
    this.percobaan += 1;
    this._reconnect = setTimeout(() => this.sambung(), jeda);
  }

  _sambungUlangSegera() {
    if (this.sengajaTutup) return;
    if (this.ws && this.ws.readyState === WebSocket.OPEN) return;
    clearTimeout(this._reconnect);
    this.percobaan = 0;
    this.sambung();
  }

  _mulaiHeartbeat() {
    this._hentikanHeartbeat();
    this._heartbeat = setInterval(() => this.kirim({ tipe: "ping" }), 25000);
  }

  _hentikanHeartbeat() {
    clearInterval(this._heartbeat);
    this._heartbeat = null;
  }

  kirim(payload) {
    if (this.ws && this.ws.readyState === WebSocket.OPEN) {
      this.ws.send(JSON.stringify(payload));
      return true;
    }
    // Jawaban yang gagal terkirim disimpan dan dikirim ulang saat reconnect.
    if (payload.tipe === "jawab") this._antrian.push(payload);
    return false;
  }

  tutup() {
    this.sengajaTutup = true;
    clearTimeout(this._reconnect);
    this._hentikanHeartbeat();
    // Penutupan disengaja bukan gangguan koneksi — indikatornya ikut dilepas.
    this.indikator.sembunyikan();
    if (this.ws) this.ws.close();
  }
}

/* --------------------------------------------------------- Fireworks ---- */

let kembangApiSudahMain = false;

/**
 * Kembang api singkat di seluruh layar — dipakai sekali saat podium Quiz
 * Mode pertama kali tampil. Ditandai `sudahMain` supaya reconnect WebSocket
 * (yang mengirim ulang `sesi_selesai`) tidak memicunya berkali-kali.
 */
export function mainkanKembangApi() {
  if (kembangApiSudahMain || gerakDikurangi()) return;
  kembangApiSudahMain = true;

  const canvas = document.createElement("canvas");
  canvas.className = "kembang-api-overlay";
  document.body.appendChild(canvas);
  const ctx = canvas.getContext("2d");
  const ukur = () => {
    canvas.width = window.innerWidth;
    canvas.height = window.innerHeight;
  };
  ukur();
  window.addEventListener("resize", ukur);

  const warna = ["#c6f135", "#8fae1f", "#ffd166", "#ef476f", "#06d6a0", "#118ab2", "#ffffff"];
  let partikel = [];

  const letuskan = () => {
    const x = canvas.width * (0.15 + Math.random() * 0.7);
    const y = canvas.height * (0.15 + Math.random() * 0.35);
    const jumlah = 42;
    const warnaLetusan = warna[(Math.random() * warna.length) | 0];
    for (let i = 0; i < jumlah; i++) {
      const sudut = (Math.PI * 2 * i) / jumlah + Math.random() * 0.25;
      const kecepatan = 1.8 + Math.random() * 2.8;
      partikel.push({
        x, y,
        vx: Math.cos(sudut) * kecepatan,
        vy: Math.sin(sudut) * kecepatan,
        hidup: 1,
        warna: warnaLetusan,
      });
    }
  };

  let letusanTersisa = 6;
  letuskan();
  const jadwal = setInterval(() => {
    letusanTersisa -= 1;
    if (letusanTersisa <= 0) {
      clearInterval(jadwal);
      return;
    }
    letuskan();
  }, 450);

  let raf;
  const gambar = () => {
    ctx.clearRect(0, 0, canvas.width, canvas.height);
    partikel = partikel.filter((p) => p.hidup > 0);
    for (const p of partikel) {
      p.x += p.vx;
      p.y += p.vy;
      p.vy += 0.045;
      p.hidup -= 0.013;
      ctx.globalAlpha = Math.max(p.hidup, 0);
      ctx.fillStyle = p.warna;
      ctx.beginPath();
      ctx.arc(p.x, p.y, 2.8, 0, Math.PI * 2);
      ctx.fill();
    }
    ctx.globalAlpha = 1;
    raf = requestAnimationFrame(gambar);
  };
  gambar();

  setTimeout(() => {
    cancelAnimationFrame(raf);
    clearInterval(jadwal);
    window.removeEventListener("resize", ukur);
    canvas.remove();
  }, 3600);
}

/* ----------------------------------------------------------- Podium ----- */

const MEDALI_PODIUM = { 1: "🥇", 2: "🥈", 3: "🥉" };

/**
 * Podium 1-2-3 (urutan tampil: 2, 1, 3) + tabel ringkas di bawahnya, maksimal
 * 10 nama total. `data` adalah hasil `bangun_podium` dari backend: `{podium,
 * tabel}`, sudah digeser server-side supaya peringkat `milikSaya` (kalau ada)
 * selalu ikut tampil beserta 2 peringkat di bawahnya. `milikSaya` dipakai
 * untuk menyorot baris/kolom milik peserta yang sedang melihat layar ini.
 * `besar` = pakai ukuran baris tabel yang lebih besar (layar presenter,
 * proporsional dengan podium raksasa di sebelahnya) — HP peserta tetap
 * ukuran biasa karena layarnya kecil.
 */
export function bangunPodiumHtml(data, milikSaya = null, besar = false) {
  const { podium, tabel } = data;
  const disaya = (b) => milikSaya != null && b.participant_id === milikSaya;
  const kelasBaris = besar ? "papan-baris besar" : "papan-baris";

  const kolom = [podium[1], podium[0], podium[2]]
    .map((b) => {
      if (!b) return '<div class="podium-kolom podium-kosong"></div>';
      return `
        <div class="podium-kolom podium-${b.peringkat}${disaya(b) ? " saya" : ""}">
          <div class="podium-medali">${MEDALI_PODIUM[b.peringkat] || b.peringkat}</div>
          <div class="podium-nama">${escapeHtml(b.nickname)}</div>
          <div class="podium-poin">${b.poin} pts</div>
          <div class="podium-balok"><span>${b.peringkat}</span></div>
        </div>`;
    })
    .join("");

  let tabelHtml = "";
  if (tabel && tabel.length) {
    const adaLompatan = tabel[0].peringkat > 4;
    tabelHtml = `<div class="papan-lanjutan">
      ${adaLompatan ? '<div class="papan-lompat">⋯</div>' : ""}
      ${tabel
        .map(
          (b) => `
        <div class="${kelasBaris}${disaya(b) ? " saya" : ""}" data-kunci="${b.participant_id}">
          <span class="papan-peringkat">${b.peringkat}</span>
          <span class="papan-nama">${escapeHtml(b.nickname)}</span>
          <span class="papan-poin">${b.poin}</span>
        </div>`
        )
        .join("")}
    </div>`;
  }
  return `<div class="podium">${kolom}</div>${tabelHtml}`;
}

/* ------------------------------------------------------------- Lain-lain */

export const NAMA_TIPE = {
  mc: "Multiple Choice",
  word_cloud: "Word Cloud",
  rating: "Rating Scale",
};

export const KELAS_OPSI = ["opt-a", "opt-b", "opt-c", "opt-d", "opt-e", "opt-f"];

/** Opsi jawaban panjang berdesakan di kotak 2-kolom sempit — kelas ini yang
    memutuskan kapan grid pindah ke 1 kolom (baris penuh) di CSS. */
const OPSI_PANJANG = 24;
export const adaOpsiPanjang = (opsi) => opsi.some((o) => o.teks.length > OPSI_PANJANG);

export function simpanLokal(kunci, nilai) {
  try {
    localStorage.setItem(kunci, JSON.stringify(nilai));
  } catch {}
}

export function bacaLokal(kunci) {
  try {
    const isi = localStorage.getItem(kunci);
    return isi ? JSON.parse(isi) : null;
  } catch {
    return null;
  }
}

export function hapusLokal(kunci) {
  try {
    localStorage.removeItem(kunci);
  } catch {}
}
