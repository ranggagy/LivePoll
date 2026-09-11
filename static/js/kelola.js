/* Halaman kelola sesi: CRUD pertanyaan, aktifkan soal, akhiri sesi. */

import { $, $$, api, toast, NAMA_TIPE, rekamPosisi, mainkanFlip } from "./common.js";

const KODE = document.querySelector("[data-kode]").dataset.kode;

let sesi = null;
let tipe = "mc";
let sedangEdit = null;
let gambarDataUri = null;

const BATAS_UKURAN_GAMBAR = 2 * 1024 * 1024; // 2MB, disimpan sebagai base64 langsung di DB

const escapeHtml = (t) =>
  String(t ?? "").replace(/[&<>"']/g, (c) =>
    ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c])
  );

/* ------------------------------------------------------------ Muat data --- */

async function muat() {
  try {
    sesi = await api(`/api/admin/sesi/${KODE}`);
  } catch (err) {
    toast(err.message, "galat");
    return;
  }
  $("#judul-sesi").textContent = sesi.judul;
  const label = sesi.mode === "quiz" ? "Quiz Mode" : "Survey Mode";
  const status = sesi.status === "aktif" ? "" : " · SESI SELESAI";
  $("#sub-sesi").textContent =
    `${sesi.pertanyaan.length} pertanyaan · ${label} · ${sesi.jumlah_partisipan} partisipan${status}`;

  if (sesi.mode === "quiz") {
    // Quiz Mode hanya mendukung Multiple Choice bertimer.
    $("#baris-tipe").classList.add("sembunyi");
    $("#blok-durasi").classList.remove("sembunyi");
    $("#petunjuk-benar").classList.remove("sembunyi");
    tipe = "mc";
  }
  if (sesi.status !== "aktif") {
    $("#btn-tambah").disabled = true;
    $("#btn-akhiri").disabled = true;
  }
  gambarDaftar();
}

function gambarDaftar() {
  const wadah = $("#daftar-pertanyaan");
  const sebelum = rekamPosisi($$(".daftar-baris", wadah));
  wadah.replaceChildren();

  if (!sesi.pertanyaan.length) {
    wadah.innerHTML = '<div class="kosong">Belum ada pertanyaan. Tambahkan minimal satu sebelum presentasi.</div>';
    return;
  }

  sesi.pertanyaan.forEach((q, i) => {
    const el = document.createElement("div");
    el.className = "daftar-baris";
    el.dataset.kunci = String(q.id);
    if (q.id === sesi.pertanyaan_aktif_id) el.classList.add("berjalan");
    const detail = [];
    if (q.tipe === "mc") detail.push(`${q.opsi.length} opsi`);
    if (q.tipe === "rating") detail.push(`skala 1–${q.rating_maks}`);
    if (sesi.mode === "quiz") detail.push(`${q.durasi_detik} detik`);
    if (q.gambar) detail.push("🖼️ ada gambar");

    el.innerHTML = `
      <div class="tumbuh">
        <div class="daftar-judul">${i + 1}. ${escapeHtml(q.teks)}</div>
        <div class="baris baris-rapat mt-8" style="align-items:center">
          <span class="pil-tipe pil-tipe-${q.tipe}">${NAMA_TIPE[q.tipe] || q.tipe}</span>
          <span class="tag-tipe">${detail.join(" · ")}</span>
        </div>
      </div>
      <div class="daftar-aksi">
        <button class="btn btn-ikon btn-garis" data-aksi="naik" title="Naikkan urutan" ${i === 0 ? "disabled" : ""}>↑</button>
        <button class="btn btn-ikon btn-garis" data-aksi="turun" title="Turunkan urutan" ${i === sesi.pertanyaan.length - 1 ? "disabled" : ""}>↓</button>
        <button class="btn btn-kecil btn-garis" data-aksi="ubah">Ubah</button>
        <button class="btn btn-ikon btn-bahaya" data-aksi="hapus" title="Hapus">✕</button>
        <button class="btn btn-kecil ${q.id === sesi.pertanyaan_aktif_id ? "btn-utama" : ""}" data-aksi="aktifkan">
          ${q.id === sesi.pertanyaan_aktif_id ? "Aktif" : "Aktifkan"}
        </button>
      </div>`;

    el.addEventListener("click", (ev) => {
      const tombol = ev.target.closest("[data-aksi]");
      if (tombol) tanganiAksi(tombol.dataset.aksi, q, i);
    });
    wadah.appendChild(el);
  });

  mainkanFlip($$(".daftar-baris", wadah), sebelum);
}

/* --------------------------------------------------------------- Aksi ---- */

async function tanganiAksi(aksi, q, indeks) {
  if (aksi === "aktifkan") {
    try {
      await api(`/api/admin/sesi/${KODE}/aktifkan/${q.id}`, { method: "POST" });
      sesi.pertanyaan_aktif_id = q.id;
      gambarDaftar();
      toast("Pertanyaan diaktifkan", "sukses");
    } catch (err) {
      toast(err.message, "galat");
    }
  } else if (aksi === "hapus") {
    if (!confirm(`Hapus pertanyaan "${q.teks}"?`)) return;
    try {
      await api(`/api/admin/pertanyaan/${q.id}`, { method: "DELETE" });
      sesi.pertanyaan = sesi.pertanyaan.filter((x) => x.id !== q.id);
      gambarDaftar();
      toast("Pertanyaan dihapus");
    } catch (err) {
      toast(err.message, "galat");
    }
  } else if (aksi === "ubah") {
    bukaForm(q);
  } else if (aksi === "naik" || aksi === "turun") {
    const tujuan = aksi === "naik" ? indeks - 1 : indeks + 1;
    if (tujuan < 0 || tujuan >= sesi.pertanyaan.length) return;
    const daftar = sesi.pertanyaan.slice();
    [daftar[indeks], daftar[tujuan]] = [daftar[tujuan], daftar[indeks]];
    sesi.pertanyaan = daftar;
    gambarDaftar();
    try {
      await api(`/api/admin/sesi/${KODE}/urutan`, { method: "POST", body: { urutan: daftar.map((x) => x.id) } });
    } catch (err) {
      toast(err.message, "galat");
    }
  }
}

$("#btn-akhiri").addEventListener("click", async () => {
  if (!confirm("Akhiri sesi ini? Partisipan tidak bisa menjawab lagi setelah ditutup.")) return;
  try {
    await api(`/api/admin/sesi/${KODE}/akhiri`, { method: "POST" });
    toast("Sesi diakhiri", "sukses");
    setTimeout(() => location.reload(), 600);
  } catch (err) {
    toast(err.message, "galat");
  }
});

$("#btn-reset").addEventListener("click", async () => {
  if (
    !confirm(
      "Reset sesi ini ke awal? Semua jawaban, skor, dan partisipan yang sudah gabung akan dihapus — pertanyaan tetap ada dan sesi bisa dipakai ulang dari kode yang sama."
    )
  )
    return;
  try {
    await api(`/api/admin/sesi/${KODE}/reset`, { method: "POST" });
    toast("Sesi direset, siap dipakai ulang", "sukses");
    setTimeout(() => location.reload(), 600);
  } catch (err) {
    toast(err.message, "galat");
  }
});

$("#btn-hapus").addEventListener("click", async () => {
  if (!confirm(`Hapus sesi "${sesi.judul}" secara permanen? Tindakan ini tidak bisa dibatalkan.`)) return;
  try {
    await api(`/api/admin/sesi/${KODE}`, { method: "DELETE" });
    toast("Sesi dihapus", "sukses");
    location.href = "/admin";
  } catch (err) {
    toast(err.message, "galat");
  }
});

/* --------------------------------------------------------------- Form ---- */

function barisOpsi(nilai = "", benar = false) {
  const el = document.createElement("div");
  el.className = "baris baris-rapat opsi-baris-form";
  el.style.alignItems = "center";
  el.innerHTML = `
    <input class="input tumbuh" maxlength="300" placeholder="Tulis pilihan jawaban…" value="${escapeHtml(nilai)}">
    <button class="btn btn-ikon ${benar ? "btn-utama" : "btn-garis"} tandai-benar ${sesi && sesi.mode === "quiz" ? "" : "sembunyi"}"
            type="button" title="Tandai sebagai jawaban benar" aria-pressed="${benar}">✓</button>
    <button class="btn btn-ikon btn-garis buang-opsi" type="button" title="Hapus opsi">✕</button>`;

  el.querySelector(".tandai-benar").addEventListener("click", (ev) => {
    // Tepat satu jawaban benar per soal.
    $$(".tandai-benar", $("#daftar-opsi")).forEach((b) => {
      b.classList.remove("btn-utama");
      b.classList.add("btn-garis");
      b.setAttribute("aria-pressed", "false");
    });
    const b = ev.currentTarget;
    b.classList.add("btn-utama");
    b.classList.remove("btn-garis");
    b.setAttribute("aria-pressed", "true");
  });

  el.querySelector(".buang-opsi").addEventListener("click", () => {
    if ($$(".opsi-baris-form", $("#daftar-opsi")).length <= 2) {
      toast("Minimal 2 pilihan jawaban", "galat");
      return;
    }
    el.animate([{ opacity: 1 }, { opacity: 0, transform: "translateX(16px)" }], {
      duration: 180,
      easing: "ease-in",
      fill: "forwards",
    }).onfinish = () => el.remove();
  });

  return el;
}

function setTipe(nilai) {
  tipe = nilai;
  $$("#pilih-tipe .pil").forEach((p) => p.setAttribute("aria-pressed", String(p.dataset.tipe === nilai)));
  $("#blok-opsi").classList.toggle("sembunyi", nilai !== "mc");
  $("#blok-rating").classList.toggle("sembunyi", nilai !== "rating");
}

$$("#pilih-tipe .pil").forEach((p) => p.addEventListener("click", () => setTipe(p.dataset.tipe)));
$("#btn-tambah-opsi").addEventListener("click", () => {
  const el = barisOpsi();
  $("#daftar-opsi").appendChild(el);
  el.querySelector("input").focus();
  el.animate([{ opacity: 0, transform: "translateY(-6px)" }, { opacity: 1, transform: "translateY(0)" }], {
    duration: 220,
    easing: "cubic-bezier(0.22,1,0.36,1)",
  });
});

function bukaForm(q = null) {
  sedangEdit = q;
  const panel = $("#panel-form");
  panel.classList.remove("sembunyi");
  $("#form-judul").textContent = q ? "Ubah pertanyaan" : "Pertanyaan baru";
  $("#teks").value = q ? q.teks : "";
  $("#rating-maks").value = q ? q.rating_maks : 5;
  $("#durasi").value = q ? q.durasi_detik : 20;
  setTipe(q ? q.tipe : sesi.mode === "quiz" ? "mc" : "mc");

  gambarDataUri = (q && q.gambar) || null;
  $("#input-gambar").value = "";
  perbaruiPratinjauGambar();

  const wadah = $("#daftar-opsi");
  wadah.replaceChildren();
  const opsi = q && q.opsi.length ? q.opsi : [{ teks: "", is_benar: false }, { teks: "", is_benar: false }];
  opsi.forEach((o) => wadah.appendChild(barisOpsi(o.teks, o.is_benar)));

  panel.scrollIntoView({ behavior: "smooth", block: "nearest" });
  $("#teks").focus();
}

$("#btn-tambah").addEventListener("click", () => bukaForm(null));
$("#btn-batal").addEventListener("click", () => $("#panel-form").classList.add("sembunyi"));

/* ------------------------------------------------------------- Gambar --- */

function perbaruiPratinjauGambar() {
  const pratinjau = $("#pratinjau-gambar");
  const btnHapus = $("#btn-hapus-gambar");
  if (gambarDataUri) {
    pratinjau.src = gambarDataUri;
    pratinjau.classList.remove("sembunyi");
    btnHapus.classList.remove("sembunyi");
  } else {
    pratinjau.classList.add("sembunyi");
    pratinjau.src = "";
    btnHapus.classList.add("sembunyi");
  }
}

$("#btn-pilih-gambar").addEventListener("click", () => $("#input-gambar").click());

$("#btn-hapus-gambar").addEventListener("click", () => {
  gambarDataUri = null;
  $("#input-gambar").value = "";
  perbaruiPratinjauGambar();
});

$("#input-gambar").addEventListener("change", () => {
  const berkas = $("#input-gambar").files[0];
  if (!berkas) return;
  if (!berkas.type.startsWith("image/")) {
    toast("File harus berupa gambar", "galat");
    return;
  }
  if (berkas.size > BATAS_UKURAN_GAMBAR) {
    toast("Ukuran gambar maksimal 2MB", "galat");
    return;
  }
  const pembaca = new FileReader();
  pembaca.onload = () => {
    gambarDataUri = pembaca.result;
    perbaruiPratinjauGambar();
  };
  pembaca.readAsDataURL(berkas);
});

$("#form-pertanyaan").addEventListener("submit", async (e) => {
  e.preventDefault();
  const tombol = $("#btn-simpan");
  const muatan = {
    tipe,
    teks: $("#teks").value.trim(),
    durasi_detik: Number($("#durasi").value) || 20,
    rating_maks: Number($("#rating-maks").value) || 5,
    gambar: gambarDataUri,
    opsi: [],
  };
  if (tipe === "mc") {
    muatan.opsi = $$(".opsi-baris-form", $("#daftar-opsi"))
      .map((baris) => ({
        teks: baris.querySelector("input").value.trim(),
        is_benar: baris.querySelector(".tandai-benar").getAttribute("aria-pressed") === "true",
      }))
      .filter((o) => o.teks);
    if (muatan.opsi.length < 2) return toast("Minimal 2 pilihan jawaban", "galat");
    if (sesi.mode === "quiz" && !muatan.opsi.some((o) => o.is_benar))
      return toast("Tandai satu jawaban benar dengan tombol ✓", "galat");
  }

  tombol.disabled = true;
  try {
    if (sedangEdit) {
      const baru = await api(`/api/admin/pertanyaan/${sedangEdit.id}`, { method: "PUT", body: muatan });
      sesi.pertanyaan = sesi.pertanyaan.map((x) => (x.id === baru.id ? baru : x));
      toast("Pertanyaan diperbarui", "sukses");
    } else {
      const baru = await api(`/api/admin/sesi/${KODE}/pertanyaan`, { method: "POST", body: muatan });
      sesi.pertanyaan.push(baru);
      toast("Pertanyaan ditambahkan", "sukses");
    }
    $("#panel-form").classList.add("sembunyi");
    gambarDaftar();
    $("#sub-sesi").textContent = $("#sub-sesi").textContent.replace(/^\d+/, String(sesi.pertanyaan.length));
  } catch (err) {
    toast(err.message, "galat");
  } finally {
    tombol.disabled = false;
  }
});

muat();
