#!/usr/bin/env python3
#
# multimodal_api_client.py - A versatile script for sending multimodal requests (images/text)
# with configurable endpoints and API keys
#
import argparse
import base64
import json
import os
import requests
from typing import Dict, Any, Optional

def encode_image(image_path: str) -> str:
    """Encode an image file to base64."""
    with open(image_path, "rb") as image_file:
        return base64.b64encode(image_file.read()).decode('utf-8')

def create_payload(model: str, text_prompt: str, image_path: Optional[str] = None) -> Dict[str, Any]:
    """Create a payload for multimodal requests."""
    payload = {
        "model": model,
        "messages": [
            {
                "role": "user",
                "content": []
            }
        ]
    }

    # Add text content
    text_content = {
        "type": "text",
        "text": text_prompt
    }
    payload["messages"][0]["content"].append(text_content)

    # Add image content if provided
    if image_path:
        if not os.path.exists(image_path):
            raise FileNotFoundError(f"Image file not found: {image_path}")

        image_extension = os.path.splitext(image_path)[1].lower()
        mime_type = f"image/{image_extension[1:] if image_extension[1:] != 'jpg' else 'jpeg'}"

        image_content = {
            "type": "image_url",
            "image_url": {
                "url": f"data:{mime_type};base64,{encode_image(image_path)}"
            }
        }
        payload["messages"][0]["content"].append(image_content)

    return payload

def send_multimodal_request(
    url: str,
    api_key: str,
    model: str,
    text_prompt: str,
    image_path: Optional[str] = None,
    headers: Optional[Dict[str, str]] = None
) -> Dict[str, Any]:
    """Send a multimodal request to the specified API endpoint."""
    payload = create_payload(model, text_prompt, image_path)

    # Prepare headers
    request_headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json"
    }

    if headers:
        request_headers.update(headers)

    try:
        response = requests.post(url, headers=request_headers, json=payload)
        response.raise_for_status()
        return response.json()
    except requests.exceptions.RequestException as e:
        print(f"Error making request: {e}")
        if hasattr(e, 'response') and e.response is not None:
            print(f"Response content: {e.response.text}")
        raise

def main():
    parser = argparse.ArgumentParser(description="Multimodal API Client - Send text and image requests to various endpoints")
    parser.add_argument("--url", required=True, help="API endpoint URL")
    parser.add_argument("--api-key", required=True, help="API key for authentication")
    parser.add_argument("--model", required=True, help="Model name to use")
    parser.add_argument("--prompt", required=True, help="Text prompt to send")
    parser.add_argument("--image", help="Path to image file to include in the request")
    parser.add_argument("--output", help="File to save the response to")
    parser.add_argument("--custom-header", action="append", help="Custom headers in format 'Header-Key:Value'")

    args = parser.parse_args()

    # Parse custom headers if provided
    headers = {}
    if args.custom_header:
        for header_str in args.custom_header:
            parts = header_str.split(':', 1)
            if len(parts) == 2:
                headers[parts[0].strip()] = parts[1].strip()
            else:
                print(f"Warning: Invalid header format: {header_str}. Expected 'Key:Value'")

    try:
        result = send_multimodal_request(
            url=args.url,
            api_key=args.api_key,
            model=args.model,
            text_prompt=args.prompt,
            image_path=args.image,
            headers=headers
        )

        # Print or save the result
        result_json = json.dumps(result, indent=2, ensure_ascii=False)

        if args.output:
            with open(args.output, 'w', encoding='utf-8') as f:
                f.write(result_json)
            print(f"Response saved to {args.output}")
        else:
            print(result_json)

    except Exception as e:
        print(f"Failed to send request: {e}")
        exit(1)

if __name__ == "__main__":
    main()