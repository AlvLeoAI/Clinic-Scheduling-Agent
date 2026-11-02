# Viewer -> CloudFront (HTTPS, default *.cloudfront.net certificate) -> VPC origin ->
# internal ALB (HTTP inside the VPC) -> UI task. The ALB has no public address, so
# CloudFront is the only way in.

resource "aws_lb" "ui" {
  #checkov:skip=CKV_AWS_91:Access logs need a log bucket; CloudFront is the only client.
  #checkov:skip=CKV_AWS_150:Deletion protection off so terraform destroy tears the demo down.
  #checkov:skip=CKV2_AWS_28:WAF is the planned control for continuous or live-mode runs (docs/SECURITY_PRIVACY.md).
  #checkov:skip=CKV2_AWS_20:Internal ALB behind CloudFront, which terminates TLS and redirects HTTP.
  name                       = "clinic-ui"
  internal                   = true
  load_balancer_type         = "application"
  subnets                    = aws_subnet.private[*].id
  security_groups            = [aws_security_group.alb.id]
  idle_timeout               = 300 # long-lived Streamlit websockets
  drop_invalid_header_fields = true
  enable_deletion_protection = false
}

resource "aws_lb_target_group" "ui" {
  #checkov:skip=CKV_AWS_378:Hop inside the VPC from the internal ALB to the UI task; TLS ends at CloudFront.
  name                 = "clinic-ui"
  port                 = 8501
  protocol             = "HTTP"
  target_type          = "ip"
  vpc_id               = aws_vpc.main.id
  deregistration_delay = 30

  health_check {
    path                = "/_stcore/health"
    matcher             = "200"
    interval            = 30
    timeout             = 5
    healthy_threshold   = 2
    unhealthy_threshold = 3
  }

  # Keeps a browser on one task while a deploy briefly runs two.
  stickiness {
    type            = "lb_cookie"
    cookie_duration = 86400
    enabled         = true
  }
}

resource "aws_lb_listener" "http" {
  #checkov:skip=CKV_AWS_2:Internal listener reached only by CloudFront VPC-origin interfaces; TLS ends at CloudFront.
  #checkov:skip=CKV_AWS_103:No TLS listener; see CKV_AWS_2.
  load_balancer_arn = aws_lb.ui.arn
  port              = 80
  protocol          = "HTTP"

  default_action {
    type             = "forward"
    target_group_arn = aws_lb_target_group.ui.arn
  }
}

resource "aws_cloudfront_vpc_origin" "ui" {
  vpc_origin_endpoint_config {
    name                   = "clinic-ui"
    arn                    = aws_lb.ui.arn
    http_port              = 80
    https_port             = 443
    origin_protocol_policy = "http-only"

    origin_ssl_protocols {
      items    = ["TLSv1.2"]
      quantity = 1
    }
  }
}

data "aws_cloudfront_cache_policy" "disabled" {
  name = "Managed-CachingDisabled"
}

# Forwards Host, cookies, query strings and the WebSocket upgrade headers, so
# Streamlit's same-origin and XSRF checks see the CloudFront hostname.
data "aws_cloudfront_origin_request_policy" "all_viewer" {
  name = "Managed-AllViewer"
}

resource "aws_cloudfront_response_headers_policy" "security" {
  #checkov:skip=CKV_AWS_259:HSTS is one year with includeSubDomains; preload is withheld because *.cloudfront.net cannot be submitted to the preload list.
  name = "clinic-ui-security-headers"

  security_headers_config {
    strict_transport_security {
      access_control_max_age_sec = 31536000
      include_subdomains         = true
      preload                    = false
      override                   = true
    }
    content_type_options {
      override = true
    }
    frame_options {
      frame_option = "DENY"
      override     = true
    }
    referrer_policy {
      referrer_policy = "strict-origin-when-cross-origin"
      override        = true
    }
  }
}

resource "aws_cloudfront_distribution" "ui" {
  #checkov:skip=CKV_AWS_305:Streamlit serves / itself; there is no static root object.
  #checkov:skip=CKV_AWS_68:WAF is the planned control for continuous or live-mode runs (docs/SECURITY_PRIVACY.md).
  #checkov:skip=CKV2_AWS_47:See CKV_AWS_68.
  #checkov:skip=CKV_AWS_86:Access logs need a log bucket; not kept for a demo.
  #checkov:skip=CKV_AWS_174:The default *.cloudfront.net certificate does not allow setting a minimum protocol.
  #checkov:skip=CKV2_AWS_42:Default certificate by decision (no custom domain).
  #checkov:skip=CKV_AWS_310:Single origin; no failover target exists.
  #checkov:skip=CKV_AWS_374:No geo restriction for a public demo.
  enabled         = true
  comment         = "Clinic Scheduling Agent demo UI"
  price_class     = "PriceClass_100"
  http_version    = "http2and3"
  is_ipv6_enabled = true

  origin {
    origin_id   = "ui"
    domain_name = aws_lb.ui.dns_name

    vpc_origin_config {
      vpc_origin_id            = aws_cloudfront_vpc_origin.ui.id
      origin_keepalive_timeout = 5
      origin_read_timeout      = 60
    }
  }

  default_cache_behavior {
    target_origin_id           = "ui"
    viewer_protocol_policy     = "redirect-to-https"
    allowed_methods            = ["GET", "HEAD", "OPTIONS", "PUT", "POST", "PATCH", "DELETE"]
    cached_methods             = ["GET", "HEAD"]
    cache_policy_id            = data.aws_cloudfront_cache_policy.disabled.id
    origin_request_policy_id   = data.aws_cloudfront_origin_request_policy.all_viewer.id
    response_headers_policy_id = aws_cloudfront_response_headers_policy.security.id
    compress                   = true
  }

  restrictions {
    geo_restriction {
      restriction_type = "none"
    }
  }

  viewer_certificate {
    cloudfront_default_certificate = true
  }
}
