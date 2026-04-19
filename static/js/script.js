const urlParams = new URLSearchParams(window.location.search);
const vehicle_id = Number(urlParams.get("vehicle_id"));
const car_name = urlParams.get("car_name");

const questionEl = document.getElementById("question");

if (!vehicle_id || vehicle_id <= 0) {
  alert("Invalid vehicle QR. Please rescan.");
  questionEl.innerText = "❌ Invalid QR Code";
  throw new Error("Invalid vehicle_id");
}

let isSubmitting = false;
let isDone = false;

// ================= DATA =================
let data = {
  vehicle_id,
  booking_status: "pending"
};

// ================= UI INIT =================
questionEl.innerHTML = `
  Selected Car: <b>${car_name}</b><br>
  <small>Checking vehicle availability...</small>
`;

// ================= FORM =================
const formHTML = `
  <div id="bookingForm">

    <label>👤 Full Name</label>
    <input id="name" type="text" placeholder="Enter your name">

    <label>📱 Phone Number</label>
    <input id="phone" type="text" placeholder="09XXXXXXXXX">

    <label>📅 Start Date</label>
    <input id="start_date" type="date">

    <label>📅 End Date</label>
    <input id="end_date" type="date">

    <button onclick="submitData()">Book Now</button>

  </div>
`;

// ================= DIALOG =================
function showDialog(title, message) {
  const dialog = document.createElement("div");

  dialog.className = "dialog-overlay";

  dialog.innerHTML = `
    <div class="dialog-box">
      <h3>${title}</h3>
      <p>${message}</p>
      <button onclick="this.closest('.dialog-overlay').remove()">OK</button>
    </div>
  `;

  document.body.appendChild(dialog);
}

// ================= VEHICLE VALIDATION =================
function checkVehicle() {
  fetch(`https://dismount-tactics-parasail.ngrok-free.dev/vehicle/${vehicle_id}`)
    .then(async res => {
      const result = await res.json();

      if (!res.ok) {
        throw result;
      }

      return result;
    })
    .then(vehicle => {
      // ✅ VALID VEHICLE → SHOW FORM
      questionEl.innerHTML = `
        Selected Car: <b>${vehicle.name}</b><br>
        <small>Status: ${vehicle.status}</small>
      `;

      questionEl.insertAdjacentHTML("afterend", formHTML);
    })
    .catch(() => {
      // ❌ INVALID / DELETED VEHICLE
      questionEl.innerHTML =
        "❌ <b>This vehicle is no longer available.</b><br><br>" +
        "Please contact the office or scan another vehicle.";
    });
}

// ================= VALIDATION =================
function validate() {
  const name = document.getElementById("name").value.trim();
  const phone = document.getElementById("phone").value.trim();
  const start = document.getElementById("start_date").value;
  const end = document.getElementById("end_date").value;

  if (!name || name.length < 3) {
    showDialog("⚠️ Invalid Name", "Name must be at least 3 characters");
    return false;
  }

  if (!/^09\d{9}$/.test(phone)) {
    showDialog("⚠️ Invalid Phone", "Enter valid number (09XXXXXXXXX)");
    return false;
  }

  const today = new Date().toISOString().split("T")[0];

  if (!start || start < today) {
    showDialog("⚠️ Invalid Date", "Start date cannot be in the past");
    return false;
  }

  if (!end || end < start) {
    showDialog("⚠️ Invalid Date", "End date must be after start date");
    return false;
  }

  data.name = name;
  data.phone = phone;
  data.start_date = start;
  data.end_date = end;

  return true;
}

// ================= SUBMIT =================
function submitData() {
  if (isSubmitting || isDone) return;

  if (!validate()) return;

  isSubmitting = true;

  questionEl.innerHTML = "⏳ Processing booking...";

  fetch("https://dismount-tactics-parasail.ngrok-free.dev/book", {
    method: "POST",
    headers: {
      "Content-Type": "application/json"
    },
    body: JSON.stringify(data)
  })
    .then(async res => {
      const result = await res.json();

      if (!res.ok) {
        throw result;
      }

      return result;
    })
    .then(() => {
      isDone = true;
      isSubmitting = false;

      document.getElementById("bookingForm").remove();

      questionEl.innerHTML =
        "🎉 <b>BOOKING SUCCESSFUL!</b><br><br>" +
        "Please wait for approval or go to the office for payment.<br><br>" +
        "<button onclick='location.reload()'>Book Another</button>";
    })
    .catch(err => {
      isSubmitting = false;

      const msg = (err?.error || err?.message || "").toLowerCase();

      // ================= DATE CONFLICT =================
      if (msg.includes("booked") || msg.includes("date")) {
        showDialog(
          "🚗 Car Already Booked",
          "The car is already booked for the selected dates. Please choose another schedule."
        );
      }

      // ================= VEHICLE ERROR =================
      else if (msg.includes("vehicle")) {
        showDialog("❌ Vehicle Issue", "This vehicle is no longer available.");
      }

      // ================= OTHER =================
      else {
        showDialog("❌ Booking Failed", err?.error || "Unexpected error occurred.");
      }
    });
}

// ================= START =================
checkVehicle();