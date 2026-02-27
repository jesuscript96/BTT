const fs = require('fs');
const data = JSON.parse(fs.readFileSync('/tmp/btt_data.json', 'utf8'));
let sorted = true, unique = true;
for (let i = 1; i < data.length; i++) {
  if (data[i].time < data[i-1].time) { sorted = false; console.log("Not sorted at", i, data[i].time, data[i-1].time); }
  if (data[i].time === data[i-1].time) { unique = false; console.log("Not unique at", i, data[i].time); }
}
console.log("Len:", data.length);
console.log("Sorted:", sorted);
console.log("Unique:", unique);
