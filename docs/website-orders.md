# Website orders API

The customer website sends each screen ad order here. The order shows on the dashboard's **Orders** page. Its ad file is formatted and waits in the approval queue: **website ads never play until you approve them**, even with "Auto-approve my uploads" on.

## Setup

- On the server, set `WEBSITE_API_KEY` to a random string of 32+ characters (e.g. `openssl rand -hex 32`). Without it the endpoint answers 503.
- Give the same value to the website as a **server-side secret**. Never put it in browser code.
- Files are only downloaded over HTTPS from hosts ending in `ORDER_FILE_HOSTS` (default `.supabase.co`, comma-separated). Redirects aren't followed. Files are capped at `ORDER_FILE_MAX_BYTES` (default 200 MB).

## `POST /api/website/orders`

```
Authorization: Bearer <WEBSITE_API_KEY>
Content-Type: application/json
```

```json
{
  "order_id": "LFA_1791700000000_ABCD",
  "business_name": "Mercato Italian Kitchen",
  "contact_name": "Maria Rossi",
  "email": "maria@example.com",
  "phone": "203-555-0100",
  "plan": "tablet-1",
  "plan_name": "Digital Screen Ad Network: 1 ad spot ($70 per month)",
  "city": "Stamford",
  "ad_choice": "Upload",
  "ad_text": "$10 off any dinner of $50 or more",
  "notes": "",
  "file_url": "https://<project>.supabase.co/storage/v1/object/sign/ad-uploads/LFA_.../ad.mp4?token=...",
  "file_name": "ad.mp4"
}
```

| Field | Required | Notes |
|---|---|---|
| `order_id` | yes | 1–80 characters from `A-Z a-z 0-9 _ . -`. Resending the same ID is safe: the first order is kept. |
| `business_name`, `email`, `plan` | yes | |
| `contact_name`, `phone`, `plan_name`, `city`, `ad_choice`, `ad_text`, `notes` | no | |
| `file_url` | no | A signed download link, valid for at least a few days so a failed download can be retried. Leave it out for "design it for me" orders; you attach the ad later on the Orders page. |
| `file_name` | no | Defaults to the last part of the URL. JPG, PNG, HEIC, MP4 or MOV. |

**Responses**
- `201` (new order) or `200` (`order_id` already received):
  ```json
  {"order_id": "LFA_...", "received": true, "duplicate": false, "file": "queued"}
  ```
  `file` is `queued` while the server downloads the file in the background. It's `none` when no file was sent.
- `400`: the file link isn't HTTPS on an allowed host, or the type isn't supported (e.g. PDF).
- `401`: missing or wrong key. `429`: too many wrong keys from one address.
- `422`: invalid fields (e.g. email).
- `503`: `WEBSITE_API_KEY` isn't set on the server.

The server answers right away and formats the file afterwards, so the website never waits for a video conversion. A download or conversion problem shows on the order in the dashboard, with a **Retry download** button.

## Dashboard

**Orders** lists every order:
- business, contact, plan, city and ad text
- a link to look the order up in Stripe
- the formatted ad, with **Approve ad**, **Reject**, **Preview**, **Upload the ad** (for design orders), **Retry download** and **Delete**

The menu badge counts orders waiting on you: an ad to approve, a file problem, or an ad still to design. Approving an ad doesn't put it on screens by itself. Add it to a loop.
