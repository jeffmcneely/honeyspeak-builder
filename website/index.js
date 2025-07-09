function bodyLoader() {
  loadImagesFromLambda('https://2gu6x603q8.execute-api.us-west-2.amazonaws.com/default/esl-random-EslLambdaFunction-7o9597CkuS2e');
}

async function loadImagesFromLambda(apiUrl) {
  try {
    // Call the Lambda function via API Gateway
    const response = await fetch(apiUrl, { method: 'GET' });
    const data = await response.json();

    // Assume data.images is an array of image URLs
    const images = data.images || [];
    const word = data.word
    const shortdef = data.shortdef;
    const imageContainer = document.getElementById('image-container');

    // Clear previous images
    imageContainer.replaceChildren()

    // Insert up to 3 images
    images.slice(0, 3).forEach(url => {
      const img = document.createElement('img');
      img.src = url;
      img.alt = word;
      img.className = 'image';
      imageContainer.appendChild(img);
    });
    const audioUrl = data.audio || "";
    const audioContainer = document.getElementById('audio-container');
    audioContainer.replaceChildren(); // Clear previous audio
    if (audioUrl !== "") {
      const audio = document.createElement('audio');
      audio.src = audioUrl;
      audio.controls = true; // shows play/pause controls
      audioContainer.appendChild(audio);
    }

    const femaleAudioUrl = data.female_audio || "";
    if (femaleAudioUrl !== "") {
      const div = document.createElement('div');
      div.innerText = "Female Voice:";
      audioContainer.appendChild(div);
      const femaleAudio = document.createElement('audio');
      femaleAudio.src = femaleAudioUrl;
      femaleAudio.controls = true; // shows play/pause controls
      audioContainer.appendChild(femaleAudio);
    }

    const maleAudioUrl = data.male_audio || "";
    if (maleAudioUrl !== "") {
      const div = document.createElement('div');
      div.innerText = "Male Voice:";
      audioContainer.appendChild(div);
      const maleAudio = document.createElement('audio');
      maleAudio.src = maleAudioUrl;
      maleAudio.controls = true; // shows play/pause controls
      audioContainer.appendChild(maleAudio);
    }

    const wordContainer = document.getElementById('word-container');
    wordContainer.replaceChildren(); // Clear previous content
    const h2 = document.createElement('h2');
    h2.textContent = word;
    wordContainer.appendChild(h2);
    wordContainer.appendChild(document.createTextNode(shortdef));
    document.getElementById('spinner_parent').style.display = 'none';

  } catch (err) {
    console.error('Error loading images:', err);
  }
}
