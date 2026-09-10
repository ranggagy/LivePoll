/* Layar partisipan: menjawab soal aktif, menerima hasil, dan tahan refresh/putus koneksi. */

import {
  $,
  $$,
  animasiAngka,
  aturLebar,
  bacaLokal,
  gantiTampilan,
  toast,
  CincinTimer,
  KlienSoket,
  KELAS_OPSI,
} from "./common.js";

const akar = document.querySelector("[data-kode]");
const KODE = akar.dataset.kode;
const MODE = akar.dataset.mode;
const tersimpan = bacaLokal(`livepoll:${KODE}`);

if (!tersimpan || !tersimpan.token) {
  location.replace(`/join/${KODE}`);
}

const panggung = $("#panggung");
const timer = new CincinTimer($("#timer"));

let kunciTampilan = null; // penanda tampilan yang sedang dirender
let terkunci = false; // true setelah partisipan menjawab
let idSoal = null;

const escapeHtml = (t) =>
  String(t ?? "").replace(/[&<>"']/g, (c) =>
    ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c])
  );

/** Render satu tampilan; balikan Promise elemen baru, atau null bila tidak berubah. */
function tampilkan(kunci, render) {
  if (kunciTampilan === kunci) return null;
  kunciTampilan = kunci;
  return gantiTampilan(panggung, () => {
    const el = document.createElement("div");
    render(el);
    return el;
  });
}

/* ------------------------------------------------------------- Lobi ----- */

function gambarLobi(pesan = "Tunggu presenter membuka pertanyaan…") {
  timer.sembunyikan();
  tampilkan("lobi", (el) => {
    el.className = "tengah";
    el.innerHTML = `
      <div class="lencana-hasil" style="background:var(--accent-tint);color:var(--ink)">
        <span class="titik" style="width:14px;height:14px;border-radius:50%;background:var(--ink);
              animation:denyut 1.8s cubic-bezier(0.65,0,0.35,1) infinite"></span>
      </div>
      <h2 style="font-size:19px">Kamu sudah masuk</h2>
      <p class="muted mt-8">${escapeHtml(pesan)}</p>`;
  });
}

/* --------------------------------------------------------- Pertanyaan --- */

function gambarPertanyaan(pertanyaan, sudahMenjawab, jawabanSaya) {
  idSoal = pertanyaan.id;
  terkunci = !!sudahMenjawab;
  const kunci = `soal:${pertanyaan.id}`;
  const menunggu = tampilkan(kunci, (el) => {
    el.innerHTML = `
      <div class="baris antara mb-16" style="align-items:center">
        <span class="chip">Pertanyaan ${pertanyaan.urutan_ke} dari ${pertanyaan.total_soal}</span>
        <span class="tag-tipe">${pertanyaan.tipe === "mc" ? "Pilih satu" : pertanyaan.tipe === "rating" ? "Beri nilai" : "Isi jawaban"}</span>
      </div>
      <h2 style="font-size:20px;line-height:1.3">${escapeHtml(pertanyaan.teks)}</h2>
      <div class="mt-24" id="area-jawab"></div>
      <p class="muted tengah mt-16" id="status-jawab"></p>`;
  });

  // Isi area jawaban setelah transisi masuk selesai.
  const pasang = () => {
    const area = $("#area-jawab");
    if (!area) return;
    if (pertanyaan.tipe === "mc") pasangMC(pertanyaan, area);
    else if (pertanyaan.tipe === "rating") pasangRating(pertanyaan, area);
    else pasangWordCloud(pertanyaan, area);
    if (terkunci) tandaiTerkunci(jawabanSaya);
  };
  if (menunggu) menunggu.then(pasang);
  else pasang();

  if (MODE === "quiz" && !pertanyaan.ditutup && pertanyaan.sisa_ms != null) {
    timer.mulai(pertanyaan.sisa_ms, pertanyaan.durasi);
  } else {
    timer.sembunyikan();
  }
}

function pasangMC(pertanyaan, area) {
  const kuis = MODE === "quiz";
  area.className = kuis ? "kuis-grid" : "tumpuk";
  area.replaceChildren();
  pertanyaan.opsi.forEach((o, i) => {
    const tombol = document.createElement("button");
    tombol.type = "button";
    tombol.dataset.opsi = String(o.id);
    tombol.className = kuis ? `kuis-kotak ${KELAS_OPSI[i % KELAS_OPSI.length]}` : "opsi-vote";
    tombol.innerHTML = kuis
      ? escapeHtml(o.teks)
      : `<span class="opsi-isi-bar"></span><span class="opsi-baris"><span>${escapeHtml(o.teks)}</span></span>`;
    tombol.addEventListener("click", () => pilihOpsi(tombol, o.id));
    area.appendChild(tombol);
    // Kotak jawaban masuk satu per satu, terasa hidup tanpa terlihat lambat.
    tombol.animate(
      [{ opacity: 0, transform: "translateY(10px) scale(0.97)" }, { opacity: 1, transform: "none" }],
      { duration: 300, delay: i * 45, easing: "cubic-bezier(0.34,1.56,0.64,1)", fill: "backwards" }
    );
  });
}

function pasangRating(pertanyaan, area) {
  area.className = "";
  area.innerHTML = `<div class="rating-grup" id="grup-rating"></div>
    <p class="muted tengah mt-16">1 = paling rendah · ${pertanyaan.rating_maks} = paling tinggi</p>`;
  const grup = $("#grup-rating");
  for (let n = 1; n <= pertanyaan.rating_maks; n++) {
    const tombol = document.createElement("button");
    tombol.type = "button";
    tombol.className = "rating-kotak";
    tombol.dataset.nilai = String(n);
    tombol.textContent = String(n);
    tombol.addEventListener("click", () => pilihRating(tombol, n));
    grup.appendChild(tombol);
    tombol.animate([{ opacity: 0, transform: "scale(0.8)" }, { opacity: 1, transform: "scale(1)" }], {
      duration: 280,
      delay: n * 40,
      easing: "cubic-bezier(0.34,1.56,0.64,1)",
      fill: "backwards",
    });
  }
}

function pasangWordCloud(pertanyaan, area) {
  area.className = "";
  area.innerHTML = `
    <input class="input" id="teks-jawab" maxlength="60" placeholder="cth: progresif" autocomplete="off">
    <button class="btn btn-utama btn-blok mt-16" id="btn-kirim">Kirim Jawaban</button>
    <p class="muted tengah mt-16">Jawabanmu masuk antrian approval presenter dulu</p>`;
  const kirim = () => {
    const teks = $("#teks-jawab").value.trim();
    if (!teks) {
      $("#teks-jawab").focus();
      return;
    }
    $("#btn-kirim").disabled = true;
    $("#teks-jawab").disabled = true;
    soket.kirim({ tipe: "jawab", question_id: idSoal, teks });
  };
  $("#btn-kirim").addEventListener("click", kirim);
  $("#teks-jawab").addEventListener("keydown", (e) => {
    if (e.key === "Enter") kirim();
  });
}

/* ------------------------------------------------------ Aksi menjawab --- */

function pilihOpsi(tombol, optionId) {
  if (terkunci) return;
  terkunci = true; // UI dikunci begitu diklik, tidak ada tombol "ubah jawaban"
  const semua = $$("[data-opsi]", $("#area-jawab"));
  semua.forEach((t) => {
    t.disabled = true;
    if (t === tombol) t.classList.add("terpilih");
    else t.classList.add("redup");
  });
  $("#status-jawab").textContent = "Jawaban terkirim, menunggu hasil…";
  soket.kirim({ tipe: "jawab", question_id: idSoal, option_id: optionId });
}

function pilihRating(tombol, nilai) {
  if (terkunci) return;
  terkunci = true;
  $$(".rating-kotak", $("#area-jawab")).forEach((t) => {
    t.disabled = true;
    if (t === tombol) t.classList.add("terpilih");
    else t.classList.add("redup");
  });
  $("#status-jawab").textContent = "Jawaban terkirim, menunggu hasil…";
  soket.kirim({ tipe: "jawab", question_id: idSoal, nilai });
}

function tandaiTerkunci(jawabanSaya) {
  const status = $("#status-jawab");
  if (status) {
    status.textContent = jawabanSaya && jawabanSaya.menunggu_moderasi
      ? "Jawaban terkirim, menunggu approval presenter"
      : "Jawaban terkirim, menunggu hasil…";
  }
  const area = $("#area-jawab");
  if (!area) return;
  $$("[data-opsi]", area).forEach((t) => {
    t.disabled = true;
    if (jawabanSaya && String(jawabanSaya.option_id) === t.dataset.opsi) t.classList.add("terpilih");
    else t.classList.add("redup");
  });
  $$(".rating-kotak", area).forEach((t) => {
    t.disabled = true;
    if (jawabanSaya && String(jawabanSaya.nilai_rating) === t.dataset.nilai) t.classList.add("terpilih");
    else t.classList.add("redup");
  });
  const input = $("#teks-jawab");
  if (input) {
    input.disabled = true;
    if (jawabanSaya && jawabanSaya.teks) input.value = jawabanSaya.teks;
    const btn = $("#btn-kirim");
    if (btn) btn.disabled = true;
  }
}

/* ------------------------------------------------------------ Hasil ----- */

function gambarHasilKuis(pribadi, papan) {
  timer.sembunyikan();
  kunciTampilan = `hasil:${idSoal}`;
  const menunggu = gantiTampilan(panggung, () => {
    const el = document.createElement("div");
    el.className = "tengah";
    const benar = pribadi && pribadi.benar;
    const menjawab = pribadi && pribadi.menjawab;
    el.innerHTML = `
      <div class="lencana-hasil ${benar ? "" : "salah"}">${benar ? "✓" : menjawab ? "✕" : "—"}</div>
      <div class="tebal" style="font-size:15px;color:${benar ? "var(--accent-deep)" : "var(--danger)"}">
        ${benar ? "Jawaban Benar" : menjawab ? "Jawaban Salah" : "Tidak Sempat Menjawab"}
      </div>
      <div class="angka-besar mt-8" id="poin-didapat">+0</div>
      <div class="muted">poin diperoleh</div>
      <div class="mt-24" style="padding-top:20px;border-top:1px solid var(--line)">
        <div class="muted">Total poin kamu</div>
        <div class="tebal mt-8" style="font-size:22px">
          <span id="total-poin">0</span> pts
          ${pribadi && pribadi.peringkat ? `· Peringkat #${pribadi.peringkat}` : ""}
        </div>
      </div>
      ${papan && papan.baris.length ? `<div class="mt-24" style="text-align:left" id="papan-mini"></div>` : ""}`;
    return el;
  });

  menunggu.then(() => {
    const poin = $("#poin-didapat");
    if (poin) animasiAngka(poin, (pribadi && pribadi.poin) || 0, { awalan: "+", durasi: 900 });
    const total = $("#total-poin");
    if (total) animasiAngka(total, (pribadi && pribadi.total_poin) || 0, { durasi: 900 });
    const chip = $("#chip-poin");
    if (chip && pribadi) {
      chip.classList.remove("sembunyi");
      chip.textContent = `${pribadi.total_poin} pts`;
    }
    gambarPapanMini(papan, pribadi);
  });
}

function gambarPapanMini(papan, pribadi) {
  const wadah = $("#papan-mini");
  if (!wadah || !papan) return;
  wadah.innerHTML = `<div class="label mb-8">Leaderboard</div>`;
  papan.baris.slice(0, 5).forEach((b, i) => {
    const el = document.createElement("div");
    el.className = "papan-baris" + (b.peringkat === 1 ? " juara" : "");
    if (tersimpan && b.participant_id === tersimpan.participant_id) el.classList.add("saya");
    el.innerHTML = `<span class="papan-peringkat">${b.peringkat}</span>
      <span class="papan-nama">${escapeHtml(b.nickname)}</span>
      <span class="papan-poin">${b.poin}</span>`;
    wadah.appendChild(el);
    el.animate([{ opacity: 0, transform: "translateX(-10px)" }, { opacity: 1, transform: "none" }], {
      duration: 300,
      delay: i * 60,
      easing: "cubic-bezier(0.22,1,0.36,1)",
      fill: "backwards",
    });
  });
}

function gambarHasilSurvey(pertanyaan, hasil) {
  timer.sembunyikan();
  kunciTampilan = `hasil:${idSoal}`;
  const menunggu = gantiTampilan(panggung, () => {
    const el = document.createElement("div");
    el.innerHTML = `
      <span class="chip mb-16">Hasil</span>
      <h2 style="font-size:18px;line-height:1.3">${escapeHtml(pertanyaan.teks)}</h2>
      <div class="muted mt-8 mb-16">${hasil ? hasil.total_jawaban : 0} partisipan menjawab</div>
      <div class="tumpuk" id="hasil-survey"></div>`;
    return el;
  });

  menunggu.then(() => {
    const wadah = $("#hasil-survey");
    if (!wadah || !hasil) return;
    if (hasil.tipe === "mc") {
      const maks = Math.max(...hasil.opsi.map((o) => o.jumlah), 0);
      hasil.opsi.forEach((o) => {
        const el = document.createElement("div");
        el.className = "opsi-vote" + (o.jumlah > 0 && o.jumlah === maks ? " teratas" : "");
        el.innerHTML = `<span class="opsi-isi-bar"></span>
          <span class="opsi-baris"><span>${escapeHtml(o.teks)}</span>
          <span class="opsi-persen">${o.persen}%</span></span>`;
        wadah.appendChild(el);
        aturLebar(el.querySelector(".opsi-isi-bar"), o.persen);
      });
    } else if (hasil.tipe === "rating") {
      wadah.innerHTML = `<div class="tengah"><div class="angka-besar">${hasil.rating.rata}</div>
        <div class="muted">rata-rata dari ${hasil.rating.maks}</div></div>`;
    } else {
      wadah.innerHTML = `<div class="awan-kata">${hasil.kata
        .slice(0, 24)
        .map((k, i) => `<span class="kata ${i < 3 ? "puncak" : ""}" style="font-size:${Math.round(
          16 + Math.sqrt(k.jumlah / Math.max(...hasil.kata.map((x) => x.jumlah), 1)) * 26
        )}px">${escapeHtml(k.teks)}</span>`)
        .join("")}</div>`;
    }
  });
}

function gambarSesiSelesai(papan) {
  timer.sembunyikan();
  kunciTampilan = "selesai";
  const menunggu = gantiTampilan(panggung, () => {
    const el = document.createElement("div");
    el.className = "tengah";
    el.innerHTML = `
      <div class="lencana-hasil">✓</div>
      <h2 style="font-size:20px">Sesi telah berakhir</h2>
      <p class="muted mt-8">Terima kasih sudah berpartisipasi.</p>
      ${papan && papan.baris.length ? '<div class="mt-24" style="text-align:left" id="papan-mini"></div>' : ""}`;
    return el;
  });
  menunggu.then(() => gambarPapanMini(papan, null));
}

/* ------------------------------------------------------------ Soket ----- */

const soket = new KlienSoket(`/ws/play/${KODE}?token=${encodeURIComponent(tersimpan ? tersimpan.token : "")}`, {
  saatPesan(pesan) {
    switch (pesan.tipe) {
      case "state": {
        if (pesan.nickname) $("#label-sesi").textContent = pesan.nickname.toUpperCase();
        if (MODE === "quiz" && pesan.total_poin != null) {
          const chip = $("#chip-poin");
          chip.classList.remove("sembunyi");
          chip.textContent = `${pesan.total_poin} pts`;
        }
        if (!pesan.pertanyaan) {
          gambarLobi();
        } else if (pesan.pertanyaan.ditutup) {
          // Reconnect setelah soal ditutup: tampilkan hasil terakhir.
          idSoal = pesan.pertanyaan.id;
          if (MODE === "quiz") gambarHasilKuis(pesan.pribadi, pesan.leaderboard);
          else gambarHasilSurvey(pesan.pertanyaan, pesan.hasil);
        } else {
          gambarPertanyaan(pesan.pertanyaan, pesan.sudah_menjawab, pesan.jawaban_saya);
        }
        break;
      }
      case "pertanyaan_dibuka":
        gambarPertanyaan(pesan.pertanyaan, false, null);
        break;
      case "pertanyaan_ditutup":
        if (MODE === "quiz") gambarHasilKuis(pesan.pribadi, pesan.leaderboard);
        else gambarHasilSurvey(pesan.pertanyaan, pesan.hasil);
        break;
      case "jawaban_diterima":
        if (!pesan.ok) {
          if (pesan.sudah) {
            terkunci = true;
          } else {
            // Gagal (mis. waktu habis) — buka kunci supaya partisipan tahu statusnya.
            terkunci = false;
            $$("#area-jawab [data-opsi], #area-jawab .rating-kotak").forEach((t) => {
              t.disabled = false;
              t.classList.remove("terpilih", "redup");
            });
            const input = $("#teks-jawab");
            if (input) {
              input.disabled = false;
              const btn = $("#btn-kirim");
              if (btn) btn.disabled = false;
            }
          }
          const status = $("#status-jawab");
          if (status) status.textContent = pesan.pesan || "";
          toast(pesan.pesan || "Jawaban tidak diterima", "galat");
        } else if (pesan.menunggu_moderasi) {
          const status = $("#status-jawab");
          if (status) status.textContent = "Jawaban terkirim, menunggu approval presenter";
          toast("Jawaban terkirim", "sukses");
        }
        break;
      case "sesi_selesai":
        gambarSesiSelesai(pesan.leaderboard);
        // Sesi sudah ditutup — berhenti mencoba menyambung ulang.
        soket.tutup();
        break;
      case "token_tidak_valid":
        soket.tutup();
        location.replace(`/join/${KODE}`);
        break;
    }
  },
});
soket.sambung();
