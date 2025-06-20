# POD Accounting App

This is a small Flask app to track accounting associated with a Print On Demand business.  It's very simple in 
that it will let you upload CSV exports from Shopify, Printify, and Meta Ads Manager to ingest your orders, cost of 
goods and ad spend. It will also let you create expenses manually for things that are less frequent.

Honestly you are probably better doing these things in Excel as this is all custom for what I want it to do - but you 
are welcome to play with it if you want some automation.  

As it is dealing with money things the standard disclaimer applies: **By using any part of this code YOU take absolutely
ALL responsibility as to what comes out of it and any outputs it produces or how you use them.  In fact you should 
EXPECT things to be wrong and be ready to verify them on your own. NO effort has been made to ensure data integrity, 
correctness or security - its all on you.**

**_WARNING_**: At this point there is not even a user login screen so **DO NOT** run this on a  public IP (or even 
private if you don't fully trust everyone on your private net)

NOTE(s): 
 - This app has _very limited_ multi-currency support.  It does have the ability to look up exchange rates (with
exchangerate.host) and wants to see your API key with them in the .env file called `EXCHANGERATE_HOST_KEY`.  It's right 
now hardcoded to work for a Canada based business and will convert only from USD to CAD.

 - This was mostly written by AI in like 3 days, so you should be able to feed it to an AI if you want help to add 
things (make it suffer with what it wrote :) ). 