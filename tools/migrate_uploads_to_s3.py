#!/usr/bin/env python3
"""
Upload local files under static/uploads to S3 (if configured) and update Post.image URLs in the database.

Usage:
  - Ensure your environment variables for DB and S3 are set (same as used by the app):
      DATABASE_URL / RENDER_DATABASE_URL (if needed), AWS_S3_BUCKET, AWS_ACCESS_KEY_ID, AWS_SECRET_ACCESS_KEY, AWS_REGION
  - From project root run:
      python tools/migrate_uploads_to_s3.py

Note: This script uploads files found locally under `static/uploads/` whose Post.image points to a local path (e.g. contains 'uploads/').
If posts reference images that only exist on the remote Render instance (not in your local checkout), those files cannot be migrated from here.
"""
import os
import sys
import uuid
import mimetypes

proj_root = os.path.dirname(os.path.dirname(__file__))
sys.path.insert(0, proj_root)

from app import app, db, Post, get_s3_client


def build_s3_url(bucket, key):
    base = os.environ.get('S3_BASE_URL')
    if base:
        if '{bucket}' in base:
            return base.format(bucket=bucket).rstrip('/') + '/' + key
        return base.rstrip('/') + '/' + key
    region = os.environ.get('AWS_REGION')
    if region:
        return f'https://{bucket}.s3.{region}.amazonaws.com/{key}'
    return f'https://{bucket}.s3.amazonaws.com/{key}'


def main():
    s3 = get_s3_client()
    if not s3:
        print('No S3 client available. Please set AWS_S3_BUCKET and credentials in environment.')
        return
    bucket = os.environ.get('AWS_S3_BUCKET')
    if not bucket:
        print('Please set AWS_S3_BUCKET in environment.')
        return

    uploads_dir = os.path.join(proj_root, 'static', 'uploads')
    if not os.path.isdir(uploads_dir):
        print('No local uploads directory found at', uploads_dir)
        return

    with app.app_context():
        posts = Post.query.filter(Post.image != None).all()
        migrated = 0
        for p in posts:
            img = p.image or ''
            # skip remote urls
            if img.startswith('http'):
                continue
            # try to extract filename from common patterns
            fname = os.path.basename(img)
            local_path = os.path.join(uploads_dir, fname)
            if not os.path.exists(local_path):
                print('Local file not found for post', p.id, 'expected', local_path)
                continue
            # upload
            key = f'uploads/{uuid.uuid4().hex}_{fname}'
            content_type, _ = mimetypes.guess_type(local_path)
            try:
                s3.put_object(Bucket=bucket, Key=key, Body=open(local_path, 'rb'), ACL='public-read')
            except Exception as e:
                print('Failed to upload', local_path, e)
                continue
            url = build_s3_url(bucket, key)
            p.image = url
            db.session.add(p)
            try:
                db.session.commit()
                migrated += 1
                print('Migrated post', p.id, '->', url)
            except Exception as e:
                db.session.rollback()
                print('DB update failed for post', p.id, e)

        print('Done. Migrated', migrated, 'posts.')


if __name__ == '__main__':
    main()
