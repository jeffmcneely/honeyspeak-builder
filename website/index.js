function bodyLoader() {

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
    const container = document.getElementById('image-container');

    // Clear previous images
    container.replaceChildren()

    // Insert up to 3 images
    images.slice(0, 3).forEach(url => {
      const img = document.createElement('img');
      img.src = url;
      img.alt = word;
      img.className = 'image';
      container.appendChild(img);
    });
  } catch (err) {
    console.error('Error loading images:', err);
  }
}
