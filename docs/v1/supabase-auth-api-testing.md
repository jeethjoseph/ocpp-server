# Supabase Authentication API Testing Guide

This document provides curl examples for testing all authentication endpoints in the OCPP Server API with **REAL REQUESTS AND RESPONSES**.

## Prerequisites

1. **Configure Supabase Project:**
   - Go to your Supabase dashboard → Authentication → Settings
   - **Disable email confirmation** for testing: Set "Enable email confirmations" to OFF
   - Or set up SMTP if you want email confirmation

2. **Environment Setup:**
   Create `.env` file in backend directory:
```bash
SUPABASE_URL=https://your-project.supabase.co
SUPABASE_ANON_KEY=your-anon-key
SUPABASE_SERVICE_ROLE_KEY=your-service-role-key
SUPABASE_JWT_SECRET=your-jwt-secret
```

3. **Start the server:**
```bash
cd backend
python main.py
```

4. Server should be running on `http://localhost:8000`

## API Testing Examples

### 1. Sign Up - Create New User

```bash
curl -X POST "http://localhost:8000/auth/signup" \
  -H "Content-Type: application/json" \
  -d '{
    "email": "jeethjoseph@gmail.com",
    "password": "Ocpp@2025",
    "user_metadata": {
      "first_name": "Jeeth",
      "last_name": "Joseph",
      "role": "user"
    }
  }'
```

**ACTUAL RESPONSE (Email confirmation required):**
```json
{
  "message": "Sign up successful. Please check your email to confirm your account.",
  "user": {
    "id": "cce34234-c6cd-4345-8594-9a1646251d03",
    "email": "jeethjoseph@gmail.com",
    "user_metadata": {
      "email": "jeethjoseph@gmail.com",
      "email_verified": false,
      "first_name": "Jeeth",
      "last_name": "Joseph",
      "phone_verified": false,
      "role": "user",
      "sub": "cce34234-c6cd-4345-8594-9a1646251d03"
    },
    "created_at": "2025-07-24T09:37:00.389832+00:00"
  },
  "email_confirmation_required": true
}
```

### 2. Sign In - Authenticate Existing User

```bash
curl -X POST "http://localhost:8000/auth/signin" \
  -H "Content-Type: application/json" \
  -d '{
    "email": "jeethjoseph@gmail.com",
    "password": "Ocpp@2025"
  }'
```

**ACTUAL RESPONSE:**
```json
{
  "access_token": "eyJhbGciOiJIUzI1NiIsImtpZCI6IjVGaytoajl2ZnMzVDBWMGoiLCJ0eXAiOiJKV1QifQ.eyJpc3MiOiJodHRwczovL3RibmhqcW1lZ3BicHl0cnlla3phLnN1cGFiYXNlLmNvL2F1dGgvdjEiLCJzdWIiOiJjY2UzNDIzNC1jNmNkLTQzNDUtODU5NC05YTE2NDYyNTFkMDMiLCJhdWQiOiJhdXRoZW50aWNhdGVkIiwiZXhwIjoxNzUzMzU2NjMwLCJpYXQiOjE3NTMzNTMwMzAsImVtYWlsIjoiamVldGhqb3NlcGhAZ21haWwuY29tIiwicGhvbmUiOiIiLCJhcHBfbWV0YWRhdGEiOnsicHJvdmlkZXIiOiJlbWFpbCIsInByb3ZpZGVycyI6WyJlbWFpbCJdfSwidXNlcl9tZXRhZGF0YSI6eyJlbWFpbCI6ImplZXRoam9zZXBoQGdtYWlsLmNvbSIsImVtYWlsX3ZlcmlmaWVkIjp0cnVlLCJmaXJzdF9uYW1lIjoiSmVldGgiLCJsYXN0X25hbWUiOiJKb3NlcGgiLCJwaG9uZV92ZXJpZmllZCI6ZmFsc2UsInJvbGUiOiJ1c2VyIiwic3ViIjoiY2NlMzQyMzQtYzZjZC00MzQ1LTg1OTQtOWExNjQ2MjUxZDAzIn0sInJvbGUiOiJhdXRoZW50aWNhdGVkIiwiYWFsIjoiYWFsMSIsImFtciI6W3sibWV0aG9kIjoicGFzc3dvcmQiLCJ0aW1lc3RhbXAiOjE3NTMzNTMwMzB9XSwic2Vzc2lvbl9pZCI6IjI1NWM3MjBhLWI3MWYtNDZmZi04MjVkLTI1YmE2ZGQzNzc3MyIsImlzX2Fub255bW91cyI6ZmFsc2V9.tZ0q2UGWFp0tXnnp-9vIxUNZVyjCAhayLFWrlXq6t9A",
  "refresh_token": "3v2zbkdxeu25",
  "user": {
    "id": "cce34234-c6cd-4345-8594-9a1646251d03",
    "email": "jeethjoseph@gmail.com",
    "user_metadata": {
      "email": "jeethjoseph@gmail.com",
      "email_verified": true,
      "first_name": "Jeeth",
      "last_name": "Joseph",
      "phone_verified": false,
      "role": "user",
      "sub": "cce34234-c6cd-4345-8594-9a1646251d03"
    },
    "created_at": "2025-07-24T09:37:00.389832Z"
  },
  "expires_in": 3600
}
```

### 3. Get Current User Info (Protected Endpoint)

**Replace `YOUR_ACCESS_TOKEN` with the actual token from sign in response.**

```bash
curl -X GET "http://localhost:8000/auth/me" \
  -H "Authorization: Bearer eyJhbGciOiJIUzI1NiIsImtpZCI6IjVGaytoajl2ZnMzVDBWMGoiLCJ0eXAiOiJKV1QifQ.eyJpc3MiOiJodHRwczovL3RibmhqcW1lZ3BicHl0cnlla3phLnN1cGFiYXNlLmNvL2F1dGgvdjEiLCJzdWIiOiJjY2UzNDIzNC1jNmNkLTQzNDUtODU5NC05YTE2NDYyNTFkMDMiLCJhdWQiOiJhdXRoZW50aWNhdGVkIiwiZXhwIjoxNzUzMzU2NjMwLCJpYXQiOjE3NTMzNTMwMzAsImVtYWlsIjoiamVldGhqb3NlcGhAZ21haWwuY29tIiwicGhvbmUiOiIiLCJhcHBfbWV0YWRhdGEiOnsicHJvdmlkZXIiOiJlbWFpbCIsInByb3ZpZGVycyI6WyJlbWFpbCJdfSwidXNlcl9tZXRhZGF0YSI6eyJlbWFpbCI6ImplZXRoam9zZXBoQGdtYWlsLmNvbSIsImVtYWlsX3ZlcmlmaWVkIjp0cnVlLCJmaXJzdF9uYW1lIjoiSmVldGgiLCJsYXN0X25hbWUiOiJKb3NlcGgiLCJwaG9uZV92ZXJpZmllZCI6ZmFsc2UsInJvbGUiOiJ1c2VyIiwic3ViIjoiY2NlMzQyMzQtYzZjZC00MzQ1LTg1OTQtOWExNjQ2MjUxZDAzIn0sInJvbGUiOiJhdXRoZW50aWNhdGVkIiwiYWFsIjoiYWFsMSIsImFtciI6W3sibWV0aG9kIjoicGFzc3dvcmQiLCJ0aW1lc3RhbXAiOjE3NTMzNTMwMzB9XSwic2Vzc2lvbl9pZCI6IjI1NWM3MjBhLWI3MWYtNDZmZi04MjVkLTI1YmE2ZGQzNzc3MyIsImlzX2Fub255bW91cyI6ZmFsc2V9.tZ0q2UGWFp0tXnnp-9vIxUNZVyjCAhayLFWrlXq6t9A"
```

**ACTUAL RESPONSE:**
```json
{
  "id": "cce34234-c6cd-4345-8594-9a1646251d03",
  "email": "jeethjoseph@gmail.com",
  "user_metadata": {
    "email": "jeethjoseph@gmail.com",
    "email_verified": true,
    "first_name": "Jeeth",
    "last_name": "Joseph",
    "phone_verified": false,
    "role": "user",
    "sub": "cce34234-c6cd-4345-8594-9a1646251d03"
  },
  "created_at": "2025-07-24 09:37:00.389832+00:00"
}
```

### 4. Logout (Protected Endpoint)

```bash
curl -X POST "http://localhost:8000/auth/logout" \
  -H "Authorization: Bearer eyJhbGciOiJIUzI1NiIsImtpZCI6IjVGaytoajl2ZnMzVDBWMGoiLCJ0eXAiOiJKV1QifQ.eyJpc3MiOiJodHRwczovL3RibmhqcW1lZ3BicHl0cnlla3phLnN1cGFiYXNlLmNvL2F1dGgvdjEiLCJzdWIiOiJjY2UzNDIzNC1jNmNkLTQzNDUtODU5NC05YTE2NDYyNTFkMDMiLCJhdWQiOiJhdXRoZW50aWNhdGVkIiwiZXhwIjoxNzUzMzU2NjMwLCJpYXQiOjE3NTMzNTMwMzAsImVtYWlsIjoiamVldGhqb3NlcGhAZ21haWwuY29tIiwicGhvbmUiOiIiLCJhcHBfbWV0YWRhdGEiOnsicHJvdmlkZXIiOiJlbWFpbCIsInByb3ZpZGVycyI6WyJlbWFpbCJdfSwidXNlcl9tZXRhZGF0YSI6eyJlbWFpbCI6ImplZXRoam9zZXBoQGdtYWlsLmNvbSIsImVtYWlsX3ZlcmlmaWVkIjp0cnVlLCJmaXJzdF9uYW1lIjoiSmVldGgiLCJsYXN0X25hbWUiOiJKb3NlcGgiLCJwaG9uZV92ZXJpZmllZCI6ZmFsc2UsInJvbGUiOiJ1c2VyIiwic3ViIjoiY2NlMzQyMzQtYzZjZC00MzQ1LTg1OTQtOWExNjQ2MjUxZDAzIn0sInJvbGUiOiJhdXRoZW50aWNhdGVkIiwiYWFsIjoiYWFsMSIsImFtciI6W3sibWV0aG9kIjoicGFzc3dvcmQiLCJ0aW1lc3RhbXAiOjE3NTMzNTMwMzB9XSwic2Vzc2lvbl9pZCI6IjI1NWM3MjBhLWI3MWYtNDZmZi04MjVkLTI1YmE2ZGQzNzc3MyIsImlzX2Fub255bW91cyI6ZmFsc2V9.tZ0q2UGWFp0tXnnp-9vIxUNZVyjCAhayLFWrlXq6t9A"
```

**ACTUAL RESPONSE:**
```json
{
  "message": "Logged out successfully"
}
```

### 5. Token Refresh

```bash
curl -X POST "http://localhost:8000/auth/refresh" \
  -H "Content-Type: application/json" \
  -d '{
    "refresh_token": "3v2zbkdxeu25"
  }'
```

## Complete Test Flow Script

Here's a complete bash script that tests the entire authentication flow:

```bash
#!/bin/bash

BASE_URL="http://localhost:8000"
EMAIL="test$(date +%s)@example.com"  # Use timestamp to avoid conflicts
PASSWORD="TestPassword123!"

echo "=== Testing Authentication Flow ==="
echo "Using email: $EMAIL"

# 1. Sign up
echo "1. Testing Sign Up..."
SIGNUP_RESPONSE=$(curl -s -X POST "$BASE_URL/auth/signup" \
  -H "Content-Type: application/json" \
  -d "{
    \"email\": \"$EMAIL\",
    \"password\": \"$PASSWORD\",
    \"user_metadata\": {
      \"first_name\": \"Test\",
      \"last_name\": \"User\",
      \"role\": \"user\"
    }
  }")

echo "Sign up response: $SIGNUP_RESPONSE"

# 2. Sign in (assuming email confirmation is disabled)
echo -e "\n2. Testing Sign In..."
SIGNIN_RESPONSE=$(curl -s -X POST "$BASE_URL/auth/signin" \
  -H "Content-Type: application/json" \
  -d "{
    \"email\": \"$EMAIL\",
    \"password\": \"$PASSWORD\"
  }")

echo "Sign in response: $SIGNIN_RESPONSE"

# Extract access token (requires jq)
if command -v jq &> /dev/null; then
    ACCESS_TOKEN=$(echo $SIGNIN_RESPONSE | jq -r '.access_token')
    
    if [ "$ACCESS_TOKEN" != "null" ] && [ "$ACCESS_TOKEN" != "" ]; then
        # 3. Test protected endpoint
        echo -e "\n3. Testing Protected Endpoint (/auth/me)..."
        ME_RESPONSE=$(curl -s -X GET "$BASE_URL/auth/me" \
          -H "Authorization: Bearer $ACCESS_TOKEN")
        echo "Me response: $ME_RESPONSE"

        # 4. Test logout
        echo -e "\n4. Testing Logout..."
        LOGOUT_RESPONSE=$(curl -s -X POST "$BASE_URL/auth/logout" \
          -H "Authorization: Bearer $ACCESS_TOKEN")
        echo "Logout response: $LOGOUT_RESPONSE"
    else
        echo "No access token received - check if email confirmation is required"
    fi
else
    echo "jq not installed - cannot extract tokens automatically"
fi

echo -e "\n=== Authentication Flow Test Complete ==="
```

## Error Response Examples

### Invalid Credentials (Sign In)
```bash
curl -X POST "http://localhost:8000/auth/signin" \
  -H "Content-Type: application/json" \
  -d '{
    "email": "jeethjoseph@gmail.com",
    "password": "wrongpassword"
  }'
```

**ACTUAL RESPONSE:**
```json
{
  "detail": "Invalid email or password"
}
```

### User Already Exists (Sign Up)
```bash
# Trying to sign up with existing email
curl -X POST "http://localhost:8000/auth/signup" \
  -H "Content-Type: application/json" \
  -d '{
    "email": "jeethjoseph@gmail.com",
    "password": "password123"
  }'
```

**ACTUAL RESPONSE:**
```json
{
  "detail": "User already exists"
}
```

### Unauthorized Access (No Token)
```bash
curl -X GET "http://localhost:8000/auth/me"
```

**ACTUAL RESPONSE:**
```json
{
  "detail": "Authorization header required"
}
```

### Invalid Token
```bash
curl -X GET "http://localhost:8000/auth/me" \
  -H "Authorization: Bearer invalid_token"
```

**ACTUAL RESPONSE:**
```json
{
  "detail": "Invalid token"
}
```

## Notes

1. **Token Storage**: In production, store tokens securely in httpOnly cookies or secure storage
2. **Token Expiry**: Access tokens expire in 1 hour (3600 seconds) by default
3. **Refresh Tokens**: Use refresh tokens to get new access tokens without re-authentication
4. **CORS**: The server is configured to accept requests from `localhost:3000` for frontend integration
5. **Environment**: Make sure your Supabase project is properly configured and accessible
6. **Email Confirmation**: If enabled, users must confirm their email before they can sign in

## Frontend Integration Example

```javascript
// Sign up example
const signUp = async (email, password, metadata = {}) => {
  const response = await fetch('http://localhost:8000/auth/signup', {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
    },
    body: JSON.stringify({
      email,
      password,
      user_metadata: metadata
    })
  });

  const data = await response.json();
  
  // Check if tokens are returned (email confirmation disabled)
  if (data.access_token) {
    localStorage.setItem('access_token', data.access_token);
    localStorage.setItem('refresh_token', data.refresh_token);
    return { success: true, user: data.user };
  }
  
  // Email confirmation required
  return { success: false, message: data.message };
};

// Sign in example
const signIn = async (email, password) => {
  const response = await fetch('http://localhost:8000/auth/signin', {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
    },
    body: JSON.stringify({ email, password })
  });

  if (response.ok) {
    const data = await response.json();
    localStorage.setItem('access_token', data.access_token);
    localStorage.setItem('refresh_token', data.refresh_token);
    return { success: true, user: data.user };
  }
  
  const error = await response.json();
  return { success: false, error: error.detail };
};

// Protected API call example
const getMe = async () => {
  const token = localStorage.getItem('access_token');
  
  const response = await fetch('http://localhost:8000/auth/me', {
    headers: {
      'Authorization': `Bearer ${token}`
    }
  });

  if (response.ok) {
    return await response.json();
  }
  
  throw new Error('Authentication required');
};
```