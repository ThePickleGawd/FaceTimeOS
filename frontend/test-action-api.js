// Test script to send current action to the Cluely widget
// Run this with: node test-action-api.js

const http = require('http');

function sendCurrentAction(action) {
  const data = action;

  const options = {
    hostname: 'localhost',
    port: 3456,
    path: '/api/currentaction',
    method: 'POST',
    headers: {
      'Content-Type': 'text/plain',
      'Content-Length': Buffer.byteLength(data)
    }
  };

  const req = http.request(options, (res) => {
    console.log(`Status: ${res.statusCode}`);

    res.on('data', (chunk) => {
      console.log(`Response: ${chunk}`);
    });
  });

  req.on('error', (error) => {
    console.error(`Error: ${error.message}`);
  });

  req.write(data);
  req.end();
}

// Test with different actions
console.log('Sending test actions to Cluely widget...\n');

sendCurrentAction('Opening calendar app...');

setTimeout(() => {
  sendCurrentAction('Creating new event...');
}, 2000);

setTimeout(() => {
  sendCurrentAction('Setting event time for tomorrow at 12pm...');
}, 4000);

setTimeout(() => {
  sendCurrentAction('Event created successfully!');
}, 6000);
