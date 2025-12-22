from fastapi import APIRouter, Request, HTTPException, Depends
from fastapi.responses import JSONResponse
import stripe
import os
from supabase import create_client
import logging

router = APIRouter()
logger = logging.getLogger(__name__)

stripe.api_key = os.getenv("STRIPE_SECRET_KEY")
webhook_secret = os.getenv("STRIPE_WEBHOOK_SECRET")

supabase = create_client(
    os.getenv("SUPABASE_URL"),
    os.getenv("SUPABASE_SERVICE_KEY")  # Service key for admin operations
)

# Price IDs for your plans
PRICE_IDS = {
    "starter": os.getenv("STRIPE_PRICE_ID_STARTER"),
    "pro": os.getenv("STRIPE_PRICE_ID_PRO")
}

@router.post("/create-checkout-session")
async def create_checkout_session(request: Request):
    """Create Stripe checkout session"""
    data = await request.json()
    user_id = data.get("user_id")
    email = data.get("email")
    plan = data.get("plan")  # "starter" or "pro"
    
    if not user_id or not email or plan not in PRICE_IDS:
        raise HTTPException(status_code=400, detail="Invalid request")
    
    try:
        # Create checkout session
        checkout_session = stripe.checkout.Session.create(
            customer_email=email,
            client_reference_id=user_id,  # Link to your Supabase user
            line_items=[{
                'price': PRICE_IDS[plan],
                'quantity': 1,
            }],
            mode='subscription',
            success_url=f"{os.getenv('FRONTEND_URL')}/dashboard?success=true",
            cancel_url=f"{os.getenv('FRONTEND_URL')}/pricing?canceled=true",
            metadata={
                'user_id': user_id,
                'plan': plan
            }
        )
        
        logger.info(f"Created checkout session for user {user_id}")
        return {"url": checkout_session.url}
    
    except Exception as e:
        logger.error(f"Error creating checkout: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/create-portal-session")
async def create_portal_session(request: Request):
    """Create customer portal session for managing subscription"""
    data = await request.json()
    user_id = data.get("user_id")
    
    if not user_id:
        raise HTTPException(status_code=400, detail="User ID required")
    
    try:
        # Get user's Stripe customer ID from Supabase profiles table
        result = supabase.table("profiles").select("stripe_customer_id").eq("id", user_id).single().execute()
        
        if not result.data or not result.data.get("stripe_customer_id"):
            raise HTTPException(status_code=404, detail="No active subscription")
        
        # Create portal session
        portal_session = stripe.billing_portal.Session.create(
            customer=result.data["stripe_customer_id"],
            return_url=f"{os.getenv('FRONTEND_URL')}/dashboard",
        )
        
        logger.info(f"Created portal session for user {user_id}")
        return {"url": portal_session.url}
    
    except Exception as e:
        logger.error(f"Error creating portal: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/webhook")
async def stripe_webhook(request: Request):
    """Handle Stripe webhooks"""
    payload = await request.body()
    sig_header = request.headers.get('stripe-signature')
    
    try:
        event = stripe.Webhook.construct_event(
            payload, sig_header, webhook_secret
        )
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid payload")
    except stripe.error.SignatureVerificationError:
        raise HTTPException(status_code=400, detail="Invalid signature")
    
    logger.info(f"Received webhook: {event['type']}")
    
    # Handle the event
    if event['type'] == 'checkout.session.completed':
        session = event['data']['object']
        handle_checkout_completed(session)
    
    elif event['type'] == 'customer.subscription.updated':
        subscription = event['data']['object']
        handle_subscription_updated(subscription)
    
    elif event['type'] == 'customer.subscription.deleted':
        subscription = event['data']['object']
        handle_subscription_deleted(subscription)
    
    elif event['type'] == 'invoice.payment_failed':
        invoice = event['data']['object']
        handle_payment_failed(invoice)
    
    return JSONResponse(content={"status": "success"})


def handle_checkout_completed(session):
    """When checkout is completed"""
    user_id = session['client_reference_id']
    customer_id = session['customer']
    subscription_id = session['subscription']
    
    # Get subscription details to determine plan
    subscription = stripe.Subscription.retrieve(subscription_id)
    price_id = subscription['items']['data'][0]['price']['id']
    
    # Determine tier based on price_id
    tier = 'starter' if price_id == PRICE_IDS['starter'] else 'pro'
    
    # Update Supabase profiles table
    supabase.table("profiles").update({
        "stripe_customer_id": customer_id,
        "stripe_subscription_id": subscription_id,
        "subscription_tier": tier,
        "subscription_status": "active"
    }).eq("id", user_id).execute()
    
    logger.info(f"✅ User {user_id} subscribed to {tier}")


def handle_subscription_updated(subscription):
    """When subscription is updated (upgrade/downgrade)"""
    customer_id = subscription['customer']
    price_id = subscription['items']['data'][0]['price']['id']
    status = subscription['status']
    
    # Determine tier
    tier = 'starter' if price_id == PRICE_IDS['starter'] else 'pro'
    
    # Update user in profiles table
    supabase.table("profiles").update({
        "subscription_tier": tier if status == "active" else "free",
        "subscription_status": status
    }).eq("stripe_customer_id", customer_id).execute()
    
    logger.info(f"✅ Subscription updated for customer {customer_id}: {tier}, {status}")


def handle_subscription_deleted(subscription):
    """When subscription is cancelled"""
    customer_id = subscription['customer']
    
    # Downgrade to free in profiles table
    supabase.table("profiles").update({
        "subscription_tier": "free",
        "subscription_status": "cancelled",
        "stripe_subscription_id": None
    }).eq("stripe_customer_id", customer_id).execute()
    
    logger.info(f"✅ Subscription cancelled for customer {customer_id}")


def handle_payment_failed(invoice):
    """When payment fails"""
    customer_id = invoice['customer']
    
    # Mark subscription as past_due but don't downgrade immediately
    # Stripe will retry payment
    supabase.table("profiles").update({
        "subscription_status": "past_due"
    }).eq("stripe_customer_id", customer_id).execute()
    
    logger.warning(f"⚠️ Payment failed for customer {customer_id}")